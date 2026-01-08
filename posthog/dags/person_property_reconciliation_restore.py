"""Dagster job for restoring person properties from backup table.

This job reads backup entries created by the reconciliation job and restores
person properties with configurable conflict resolution strategies.
"""

import json
import time
from typing import Any

from django.conf import settings

import dagster
import psycopg2
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.dags.person_property_reconciliation import publish_person_to_kafka
from posthog.kafka_client.client import _KafkaProducer

executor_def = dagster.in_process_executor if settings.DEBUG else k8s_job_executor


def ensure_dict(value: Any) -> dict:
    """Ensure a value is a dict, parsing from JSON string if needed."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}


class PersonPropertyRestoreConfig(dagster.Config):
    """Configuration for the person property restore job."""

    job_id: str  # Which backup job to restore from
    team_ids: list[int] | None = None  # Optional: filter to specific teams
    person_ids: list[int] | None = None  # Optional: filter to specific persons
    conflict_resolution: str = "keep_newer"  # "keep_newer", "restore_wins", "full_overwrite"
    dry_run: bool = False  # Log without applying


def fetch_backup_entries(
    cursor,
    job_id: str,
    team_ids: list[int] | None = None,
    person_ids: list[int] | None = None,
) -> list[dict]:
    """Fetch backup entries for restore, grouped by team."""
    query = """
        SELECT
            job_id, team_id, person_id, uuid::text,
            properties, properties_last_updated_at, properties_last_operation, version,
            is_identified, created_at, is_user_id,
            properties_after, properties_last_updated_at_after, properties_last_operation_after, version_after
        FROM posthog_person_reconciliation_backup
        WHERE job_id = %s
    """
    params: list[Any] = [job_id]

    if team_ids:
        query += " AND team_id = ANY(%s)"
        params.append(team_ids)

    if person_ids:
        query += " AND person_id = ANY(%s)"
        params.append(person_ids)

    query += " ORDER BY team_id, person_id"

    cursor.execute(query, params)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_person_by_id(cursor, team_id: int, person_id: int) -> dict | None:
    """Fetch current person state by id."""
    cursor.execute(
        """
        SELECT
            id,
            uuid::text,
            properties,
            properties_last_updated_at,
            properties_last_operation,
            version,
            is_identified,
            created_at,
            is_user_id
        FROM posthog_person
        WHERE team_id = %s AND id = %s
        """,
        (team_id, person_id),
    )
    row = cursor.fetchone()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    result = dict(zip(columns, row))
    # Ensure JSONB fields are parsed (handles both RealDictCursor and regular cursors)
    result["properties"] = ensure_dict(result.get("properties"))
    result["properties_last_updated_at"] = ensure_dict(result.get("properties_last_updated_at"))
    result["properties_last_operation"] = ensure_dict(result.get("properties_last_operation"))
    return result


def compute_restore_diff(
    current_person: dict,
    backup_before: dict,
    backup_after: dict,
    conflict_resolution: str,
) -> dict | None:
    """
    Compute what properties to restore.

    Args:
        current_person: Current state from posthog_person table
        backup_before: "Before" state from backup (what we want to restore TO)
        backup_after: "After" state from backup (what reconciliation changed it TO)
        conflict_resolution: How to handle conflicts
            - "full_overwrite": Complete replacement with backup's before state
            - "restore_wins": Restore all backed-up properties, preserve new properties added after backup
            - "keep_newer": Only restore properties unchanged since backup

    Returns:
        Dict with updated properties, or None if no changes needed.
    """
    current_props = current_person.get("properties") or {}
    backup_before_props = backup_before.get("properties") or {}
    backup_after_props = backup_after.get("properties") or {}

    if conflict_resolution == "full_overwrite":
        if current_props == backup_before_props:
            return None
        return {
            "properties": dict(backup_before_props),
            "properties_last_updated_at": dict(backup_before.get("properties_last_updated_at") or {}),
            "properties_last_operation": dict(backup_before.get("properties_last_operation") or {}),
        }

    result_properties = dict(current_props)
    result_last_updated_at = dict(current_person.get("properties_last_updated_at") or {})
    result_last_operation = dict(current_person.get("properties_last_operation") or {})
    changes_made = False

    backup_before_last_updated_at = backup_before.get("properties_last_updated_at") or {}
    backup_before_last_operation = backup_before.get("properties_last_operation") or {}

    for key, before_value in backup_before_props.items():
        current_value = current_props.get(key)
        after_value = backup_after_props.get(key)

        if conflict_resolution == "restore_wins":
            if current_value != before_value:
                result_properties[key] = before_value
                # Restore metadata to backup state (set if present, remove if not)
                if key in backup_before_last_updated_at:
                    result_last_updated_at[key] = backup_before_last_updated_at[key]
                else:
                    result_last_updated_at.pop(key, None)
                if key in backup_before_last_operation:
                    result_last_operation[key] = backup_before_last_operation[key]
                else:
                    result_last_operation.pop(key, None)
                changes_made = True

        elif conflict_resolution == "keep_newer":
            if current_value == after_value and current_value != before_value:
                result_properties[key] = before_value
                # Restore metadata to backup state (set if present, remove if not)
                if key in backup_before_last_updated_at:
                    result_last_updated_at[key] = backup_before_last_updated_at[key]
                else:
                    result_last_updated_at.pop(key, None)
                if key in backup_before_last_operation:
                    result_last_operation[key] = backup_before_last_operation[key]
                else:
                    result_last_operation.pop(key, None)
                changes_made = True

    if not changes_made:
        return None

    return {
        "properties": result_properties,
        "properties_last_updated_at": result_last_updated_at,
        "properties_last_operation": result_last_operation,
    }


def restore_person_with_version_check(
    cursor,
    team_id: int,
    person_id: int,
    person_uuid: str,
    backup_entry: dict,
    conflict_resolution: str,
    dry_run: bool = False,
    max_retries: int = 3,
) -> tuple[bool, dict | None]:
    """
    Restore a person's properties with optimistic locking.

    Args:
        cursor: Database cursor
        team_id: Team ID
        person_id: Person ID (from backup)
        person_uuid: Person UUID
        backup_entry: Backup entry with before/after state
        conflict_resolution: "keep_newer", "restore_wins", or "full_overwrite"
        dry_run: If True, don't actually write the UPDATE
        max_retries: Maximum retry attempts on version mismatch

    Returns:
        Tuple of (success: bool, updated_person_data: dict | None)
        updated_person_data contains the final state for Kafka publishing
    """
    backup_before = {
        "properties": ensure_dict(backup_entry.get("properties")),
        "properties_last_updated_at": ensure_dict(backup_entry.get("properties_last_updated_at")),
        "properties_last_operation": ensure_dict(backup_entry.get("properties_last_operation")),
    }
    backup_after = {
        "properties": ensure_dict(backup_entry.get("properties_after")),
        "properties_last_updated_at": ensure_dict(backup_entry.get("properties_last_updated_at_after")),
        "properties_last_operation": ensure_dict(backup_entry.get("properties_last_operation_after")),
    }

    for _attempt in range(max_retries):
        person = fetch_person_by_id(cursor, team_id, person_id)
        if not person:
            return False, None

        current_version = person.get("version") or 0

        update = compute_restore_diff(person, backup_before, backup_after, conflict_resolution)
        if not update:
            return True, None

        if dry_run:
            return True, None

        cursor.execute(
            """
            UPDATE posthog_person SET
                properties = %s,
                properties_last_updated_at = %s,
                properties_last_operation = %s,
                version = %s
            WHERE team_id = %s AND id = %s AND version = %s
            RETURNING uuid
            """,
            (
                json.dumps(update["properties"]),
                json.dumps(update["properties_last_updated_at"]),
                json.dumps(update["properties_last_operation"]),
                current_version + 1,
                team_id,
                person_id,
                current_version,
            ),
        )

        if cursor.rowcount > 0:
            return (
                True,
                {
                    "id": person_uuid,
                    "team_id": team_id,
                    "properties": update["properties"],
                    "is_identified": person.get("is_identified", False),
                    "is_deleted": 0,
                    "created_at": person.get("created_at"),
                    "version": current_version + 1,
                },
            )

    return False, None


@dagster.op
def get_backup_entries(
    context: dagster.OpExecutionContext,
    config: PersonPropertyRestoreConfig,
    persons_database: dagster.ResourceParam[psycopg2.extensions.connection],
) -> list[dict]:
    """Query backup table for entries to restore."""
    context.log.info(f"Fetching backup entries for job_id: {config.job_id}")

    with persons_database.cursor() as cursor:
        entries = fetch_backup_entries(cursor, config.job_id, config.team_ids, config.person_ids)

    if not entries:
        context.log.info("No backup entries found")
        return []

    team_ids = {e["team_id"] for e in entries}
    context.log.info(f"Found {len(entries)} backup entries across {len(team_ids)} teams")
    context.add_output_metadata(
        {
            "entry_count": dagster.MetadataValue.int(len(entries)),
            "team_count": dagster.MetadataValue.int(len(team_ids)),
        }
    )

    return entries


@dagster.op(out=dagster.DynamicOut(list))
def create_restore_chunks(
    context: dagster.OpExecutionContext,
    backup_entries: list[dict],
):
    """Group backup entries by team for parallel processing."""
    if not backup_entries:
        context.log.info("No entries to process")
        return

    teams: dict[int, list[dict]] = {}
    for entry in backup_entries:
        team_id = entry["team_id"]
        if team_id not in teams:
            teams[team_id] = []
        teams[team_id].append(entry)

    context.log.info(f"Creating {len(teams)} team chunks")

    for team_id, entries in teams.items():
        chunk_key = f"team_{team_id}"
        yield dagster.DynamicOutput(
            value=entries,
            mapping_key=chunk_key,
        )


@dagster.op
def restore_team_chunk(
    context: dagster.OpExecutionContext,
    config: PersonPropertyRestoreConfig,
    chunk: list[dict],
    persons_database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
    kafka_producer: dagster.ResourceParam[_KafkaProducer],
) -> dict[str, Any]:
    """Restore person properties for all backup entries in a team chunk."""
    if not chunk:
        return {"team_id": 0, "persons_processed": 0, "persons_restored": 0, "persons_skipped": 0}

    team_id = chunk[0]["team_id"]
    job_name = context.run.job_name
    chunk_id = f"team_{team_id}"
    metrics_client = MetricsClient(cluster)

    context.log.info(
        f"Starting restore for team_id={team_id}, entries={len(chunk)}, "
        f"conflict_resolution={config.conflict_resolution}"
    )

    total_processed = 0
    total_restored = 0
    total_skipped = 0

    try:
        start_time = time.time()

        with persons_database.cursor() as cursor:
            cursor.execute("SET application_name = 'person_property_restore'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '30min'")
            cursor.execute("SET synchronous_commit = off")

            persons_to_publish = []

            for backup_entry in chunk:
                person_id = backup_entry["person_id"]
                person_uuid = backup_entry["uuid"]

                success, person_data = restore_person_with_version_check(
                    cursor=cursor,
                    team_id=team_id,
                    person_id=person_id,
                    person_uuid=person_uuid,
                    backup_entry=backup_entry,
                    conflict_resolution=config.conflict_resolution,
                    dry_run=config.dry_run,
                )

                if not success:
                    context.log.warning(f"Failed to restore person after retries: {person_id}")
                    total_skipped += 1
                elif person_data:
                    persons_to_publish.append(person_data)
                    total_restored += 1
                else:
                    total_skipped += 1

                total_processed += 1

            if persons_to_publish and not config.dry_run:
                persons_database.commit()

                for person_data in persons_to_publish:
                    try:
                        publish_person_to_kafka(person_data, kafka_producer)
                    except Exception as kafka_error:
                        context.log.warning(
                            f"Failed to publish person to Kafka: {person_data['id']}, error: {kafka_error}"
                        )
                try:
                    kafka_producer.flush()
                except Exception as flush_error:
                    context.log.warning(f"Failed to flush Kafka producer: {flush_error}")

                context.log.info(f"Restored {len(persons_to_publish)} persons for team_id={team_id}")
            elif persons_to_publish and config.dry_run:
                context.log.info(f"[DRY RUN] Would restore {len(persons_to_publish)} persons for team_id={team_id}")

        duration = time.time() - start_time
        try:
            metrics_client.increment(
                "person_property_restore_persons_processed_total",
                labels={"job_name": job_name, "chunk_id": chunk_id},
                value=float(total_processed),
            ).result()
            metrics_client.increment(
                "person_property_restore_duration_seconds_total",
                labels={"job_name": job_name, "chunk_id": chunk_id},
                value=duration,
            ).result()
        except Exception:
            pass

    except Exception as e:
        error_msg = f"Error for team_id={team_id}: {e}"
        context.log.exception(error_msg)

        try:
            metrics_client.increment(
                "person_property_restore_error",
                labels={"job_name": job_name, "chunk_id": chunk_id, "reason": "error"},
                value=1.0,
            ).result()
        except Exception:
            pass

        raise dagster.Failure(
            description=error_msg,
            metadata={
                "team_id": dagster.MetadataValue.int(team_id),
                "error_message": dagster.MetadataValue.text(str(e)),
                "persons_processed_before_failure": dagster.MetadataValue.int(total_processed),
            },
        ) from e

    context.log.info(
        f"Completed team_id={team_id}: processed={total_processed}, restored={total_restored}, skipped={total_skipped}"
    )

    try:
        metrics_client.increment(
            "person_property_restore_persons_restored_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_restored),
        ).result()
        metrics_client.increment(
            "person_property_restore_persons_skipped_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_skipped),
        ).result()
    except Exception:
        pass

    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(team_id),
            "persons_processed": dagster.MetadataValue.int(total_processed),
            "persons_restored": dagster.MetadataValue.int(total_restored),
            "persons_skipped": dagster.MetadataValue.int(total_skipped),
        }
    )

    return {
        "team_id": team_id,
        "persons_processed": total_processed,
        "persons_restored": total_restored,
        "persons_skipped": total_skipped,
    }


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=executor_def,
)
def person_property_reconciliation_restore_from_backup():
    """
    Job to restore person properties from backup table.

    This job reads backup entries created by the reconciliation job and
    restores person properties. Conflict resolution options:
    - full_overwrite: Complete overwrite with backup's "before" state
    - restore_wins: Restore all backed-up properties, preserve new ones added after backup
    - keep_newer: Only restore properties unchanged since backup
    """
    backup_entries = get_backup_entries()
    chunks = create_restore_chunks(backup_entries)
    chunks.map(restore_team_chunk)
