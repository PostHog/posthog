"""Dagster job for reconciling person properties that were missed due to a bug where
PERSON_BATCH_WRITING_DB_WRITE_MODE=ASSERT_VERSION caused updatePersonAssertVersion()
to not properly merge properties.

This job reads events from ClickHouse to find property updates ($set, $set_once, $unset)
within a bug window, compares timestamps with properties_last_updated_at in Postgres,
and applies any missed updates.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import dagster
import psycopg2

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_PERSON


class PersonPropertyReconciliationConfig(dagster.Config):
    """Configuration for the person property reconciliation job."""

    bug_window_start: str  # ISO format: "2024-12-01T00:00:00Z"
    bug_window_end: str  # ISO format: "2024-12-15T00:00:00Z"
    team_ids: list[int] | None = None  # Optional: filter to specific teams
    dry_run: bool = False  # Log changes without applying


# Max concurrent team processing - controls parallelism of the dynamic mapping
MAX_CONCURRENT_TEAMS = 4


@dataclass
class PropertyUpdate:
    """A single property update from ClickHouse events."""

    key: str
    value: Any
    timestamp: datetime
    operation: str  # "set" or "set_once"


@dataclass
class PersonPropertyUpdates:
    """Aggregated property updates for a single person from ClickHouse."""

    person_id: str
    updates: list[PropertyUpdate]


def parse_datetime(dt_str: str) -> datetime:
    """Parse an ISO format datetime string."""
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def get_person_property_updates_from_clickhouse(
    team_id: int,
    bug_window_start: str,
    bug_window_end: str,
) -> list[PersonPropertyUpdates]:
    """
    Query ClickHouse to get property updates per person that differ from current state.

    This query:
    1. Joins events with person_distinct_id_overrides to resolve merged persons
    2. Extracts $set (argMax for latest) and $set_once (argMin for first) properties
    3. Compares with current person properties in ClickHouse
    4. Returns only persons where properties differ or are missing

    Returns:
        set_diff: Array of (key, value, timestamp) tuples for $set properties that differ
        set_once_diff: Array of (key, value, timestamp) tuples for $set_once properties missing
    """
    query = """
    SELECT
        with_person_props.person_id,
        -- For $set: only include properties where the key exists in person properties AND the value differs
        arrayMap(i -> (set_keys[i], set_values[i], set_timestamps[i]), arrayFilter(
            i -> (
                indexOf(keys2, set_keys[i]) > 0
                AND set_values[i] != vals2[indexOf(keys2, set_keys[i])]
            ),
            arrayEnumerate(set_keys)
        )) AS set_diff,
        -- For $set_once: only include properties where the key does NOT exist in person properties
        arrayFilter(
            kv -> indexOf(keys2, kv.1) = 0,
            arrayMap(i -> (set_once_keys[i], set_once_values[i], set_once_timestamps[i]), arrayEnumerate(set_once_keys))
        ) AS set_once_diff
    FROM (
        SELECT
            merged.person_id,
            merged.set_keys,
            merged.set_values,
            merged.set_timestamps,
            merged.set_once_keys,
            merged.set_once_values,
            merged.set_once_timestamps,
            arrayMap(x -> x.1, JSONExtractKeysAndValues(p.person_properties, 'String')) AS keys2,
            arrayMap(x -> x.2, JSONExtractKeysAndValues(p.person_properties, 'String')) AS vals2
        FROM (
            -- Extract separate arrays from grouped tuples, split by prop_type
            -- We group into tuples first to ensure array alignment
            SELECT
                person_id,
                arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_keys,
                arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_values,
                arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_timestamps,
                arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_keys,
                arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_values,
                arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_timestamps
            FROM (
                SELECT
                    person_id,
                    groupArray(tuple(key, value, kv_timestamp, prop_type)) AS grouped_props
                FROM (
                    SELECT
                        if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id) AS person_id,
                        kv_tuple.2 AS key,
                        kv_tuple.1 AS prop_type,
                        if(kv_tuple.1 = 'set', argMax(kv_tuple.3, e.timestamp), argMin(kv_tuple.3, e.timestamp)) AS value,
                        if(kv_tuple.1 = 'set', max(e.timestamp), min(e.timestamp)) AS kv_timestamp
                    FROM events e
                    LEFT OUTER JOIN (
                        SELECT
                            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                            person_distinct_id_overrides.distinct_id AS distinct_id
                        FROM person_distinct_id_overrides
                        WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
                        GROUP BY person_distinct_id_overrides.distinct_id
                        HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
                    ) AS overrides ON e.distinct_id = overrides.distinct_id
                    ARRAY JOIN
                        arrayConcat(
                            arrayMap(x -> tuple('set', x.1, x.2), JSONExtractKeysAndValues(e.properties, '$set', 'String')),
                            arrayMap(x -> tuple('set_once', x.1, x.2), JSONExtractKeysAndValues(e.properties, '$set_once', 'String'))
                        ) AS kv_tuple
                    WHERE e.team_id = %(team_id)s
                      AND e.timestamp > %(bug_window_start)s
                      AND e.timestamp < %(bug_window_end)s
                      AND (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '')
                    GROUP BY person_id, kv_tuple.2, kv_tuple.1
                )
                GROUP BY person_id
            )
        ) AS merged
        INNER JOIN (
            SELECT
                id,
                argMax(properties, version) as person_properties
            FROM person
            WHERE team_id = %(team_id)s
              AND _timestamp > %(bug_window_start)s
              AND _timestamp < %(bug_window_end)s
            GROUP BY id
        ) AS p ON p.id = merged.person_id
    ) AS with_person_props
    WHERE length(set_diff) > 0 OR length(set_once_diff) > 0
    ORDER BY with_person_props.person_id
    SETTINGS
        readonly=2,
        max_execution_time=1200,
        allow_experimental_object_type=1,
        format_csv_allow_double_quotes=0,
        max_ast_elements=4000000,
        max_expanded_ast_elements=4000000,
        max_bytes_before_external_group_by=0,
        allow_experimental_analyzer=1,
        transform_null_in=1,
        optimize_min_equality_disjunction_chain_length=4294967295,
        allow_experimental_join_condition=1,
        use_hive_partitioning=0
    """

    params = {
        "team_id": team_id,
        "bug_window_start": bug_window_start,
        "bug_window_end": bug_window_end,
    }

    rows = sync_execute(query, params)

    results: list[PersonPropertyUpdates] = []
    for row in rows:
        person_id, set_diff, set_once_diff = row

        updates: list[PropertyUpdate] = []

        # Add differing $set properties (tuples of key, value, timestamp)
        for key, value, timestamp in set_diff:
            updates.append(
                PropertyUpdate(
                    key=key,
                    value=value,
                    timestamp=timestamp,
                    operation="set",
                )
            )

        # Add missing $set_once properties (tuples of key, value, timestamp)
        for key, value, timestamp in set_once_diff:
            updates.append(
                PropertyUpdate(
                    key=key,
                    value=value,
                    timestamp=timestamp,
                    operation="set_once",
                )
            )

        if updates:
            results.append(PersonPropertyUpdates(person_id=str(person_id), updates=updates))

    return results


def reconcile_person_properties(
    person: dict,
    property_updates: list[PropertyUpdate],
) -> dict | None:
    """
    Compute updated properties by comparing ClickHouse updates with current Postgres state.

    The CH query pre-filters to only return:
    - $set properties where the CH value differs from current person state
    - $set_once properties that are missing from current person state

    Args:
        person: From Postgres with uuid, properties, properties_last_updated_at, properties_last_operation
        property_updates: List of PropertyUpdate from ClickHouse, representing potential updates

    Returns:
        Dict with updated properties/metadata if changes needed, None otherwise.
    """
    properties = dict(person["properties"] or {})
    properties_last_updated_at = dict(person["properties_last_updated_at"] or {})
    properties_last_operation = dict(person["properties_last_operation"] or {})

    changed = False

    for update in property_updates:
        key = update.key
        value = update.value
        event_ts = update.timestamp
        operation = update.operation
        event_ts_str = event_ts.isoformat()

        existing_ts_str = properties_last_updated_at.get(key)

        if operation == "set_once":
            # set_once: these are properties missing from PG that should exist
            # Only add if property doesn't already exist in PG
            if key not in properties:
                properties[key] = value
                properties_last_updated_at[key] = event_ts_str
                properties_last_operation[key] = "set_once"
                changed = True
        else:
            # set: these are properties where CH value differs from PG
            # Only update if property exists in PG and CH timestamp is newer
            if key in properties and (existing_ts_str is None or event_ts > parse_datetime(existing_ts_str)):
                properties[key] = value
                properties_last_updated_at[key] = event_ts_str
                properties_last_operation[key] = "set"
                changed = True

    if changed:
        return {
            "properties": properties,
            "properties_last_updated_at": properties_last_updated_at,
            "properties_last_operation": properties_last_operation,
        }
    return None


def publish_person_to_kafka(person_data: dict) -> None:
    """
    Publish a person update to the Kafka topic for ClickHouse ingestion.

    Args:
        person_data: Dict with id, team_id, properties, is_identified, is_deleted, created_at, version
    """
    from django.utils.timezone import now

    # Format data for Kafka/ClickHouse
    created_at = person_data.get("created_at")
    if hasattr(created_at, "strftime"):
        created_at_str = created_at.strftime("%Y-%m-%d %H:%M:%S.%f")
    else:
        created_at_str = str(created_at) if created_at else now().strftime("%Y-%m-%d %H:%M:%S.%f")

    kafka_data = {
        "id": str(person_data["id"]),
        "team_id": person_data["team_id"],
        "properties": json.dumps(person_data["properties"]),
        "is_identified": int(person_data.get("is_identified", False)),
        "is_deleted": int(person_data.get("is_deleted", 0)),
        "created_at": created_at_str,
        "version": person_data["version"],
        "_timestamp": now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    producer = KafkaProducer()
    producer.produce(topic=KAFKA_PERSON, data=kafka_data)


def fetch_person_from_postgres(cursor, team_id: int, person_uuid: str) -> dict | None:
    """Fetch a single person record from Postgres."""
    cursor.execute(
        """
        SELECT
            uuid::text,
            properties,
            properties_last_updated_at,
            properties_last_operation,
            version,
            is_identified,
            created_at
        FROM posthog_person
        WHERE team_id = %s AND uuid = %s::uuid
        """,
        (team_id, person_uuid),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def update_person_with_version_check(
    cursor,
    team_id: int,
    person_uuid: str,
    property_updates: list[PropertyUpdate],
    dry_run: bool = False,
    max_retries: int = 3,
) -> tuple[bool, dict | None]:
    """
    Update a person's properties with optimistic locking.

    Fetches the person, computes updates, and writes with version check.
    If version changed (concurrent modification), re-fetches and retries.

    Args:
        cursor: Database cursor
        team_id: Team ID
        person_uuid: Person UUID
        property_updates: Property updates from ClickHouse
        dry_run: If True, don't actually write
        max_retries: Maximum retry attempts on version mismatch

    Returns:
        Tuple of (success: bool, updated_person_data: dict | None)
        updated_person_data contains the final state for Kafka publishing
    """
    for _attempt in range(max_retries):
        # Fetch current person state
        person = fetch_person_from_postgres(cursor, team_id, person_uuid)
        if not person:
            return False, None

        current_version = person.get("version") or 0

        # Compute updates
        update = reconcile_person_properties(person, property_updates)
        if not update:
            # No changes needed
            return True, None

        if dry_run:
            return True, None

        # Write with version check
        cursor.execute(
            """
            UPDATE posthog_person SET
                properties = %s,
                properties_last_updated_at = %s,
                properties_last_operation = %s,
                version = %s
            WHERE team_id = %s AND uuid = %s::uuid AND version = %s
            RETURNING uuid
            """,
            (
                json.dumps(update["properties"]),
                json.dumps(update["properties_last_updated_at"]),
                json.dumps(update["properties_last_operation"]),
                current_version + 1,
                team_id,
                person_uuid,
                current_version,
            ),
        )

        if cursor.rowcount > 0:
            # Success - return data for Kafka publishing
            return True, {
                "id": person_uuid,
                "team_id": team_id,
                "properties": update["properties"],
                "is_identified": person.get("is_identified", False),
                "is_deleted": 0,
                "created_at": person.get("created_at"),
                "version": current_version + 1,
            }

        # Version mismatch - retry with fresh data
        # (loop will re-fetch person)

    # Exhausted retries
    return False, None


@dagster.op
def get_team_ids_to_reconcile(
    context: dagster.OpExecutionContext,
    config: PersonPropertyReconciliationConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    """
    Query ClickHouse for distinct team_ids with property-setting events in the bug window.
    """
    if config.team_ids:
        context.log.info(f"Using configured team_ids: {config.team_ids}")
        return config.team_ids

    query = """
        SELECT DISTINCT team_id
        FROM events
        WHERE timestamp >= %(bug_window_start)s
          AND timestamp < %(bug_window_end)s
          AND (
            JSONHas(properties, '$set') = 1
            OR JSONHas(properties, '$set_once') = 1
            OR JSONHas(properties, '$unset') = 1
          )
        ORDER BY team_id
    """

    context.log.info(
        f"Querying for team_ids with property events between {config.bug_window_start} and {config.bug_window_end}"
    )

    results = sync_execute(
        query,
        {
            "bug_window_start": config.bug_window_start,
            "bug_window_end": config.bug_window_end,
        },
    )

    team_ids = [int(row[0]) for row in results]

    if not team_ids:
        context.log.info("No team IDs found with property events in bug window")
        return []

    context.log.info(f"Found {len(team_ids)} teams with property events")
    context.log.info(f"Sample of teams to process: {team_ids[:10]}" + ("..." if len(team_ids) > 10 else ""))
    context.add_output_metadata({"team_count": dagster.MetadataValue.int(len(team_ids))})

    return team_ids


@dagster.op(out=dagster.DynamicOut(int))
def create_team_chunks(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
):
    """
    Create a chunk for each team_id.
    Yields DynamicOutput for each team.
    """
    if not team_ids:
        context.log.info("No teams to process")
        return

    context.log.info(f"Creating {len(team_ids)} team chunks")

    for team_id in team_ids:
        chunk_key = f"team_{team_id}"
        context.log.info(f"Yielding chunk for team_id: {team_id}")
        yield dagster.DynamicOutput(
            value=team_id,
            mapping_key=chunk_key,
        )


@dagster.op
def reconcile_team_chunk(
    context: dagster.OpExecutionContext,
    config: PersonPropertyReconciliationConfig,
    chunk: int,
    database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict[str, Any]:
    """
    Reconcile person properties for all affected persons in a team.
    """
    team_id = chunk
    chunk_id = f"team_{team_id}"
    job_name = context.run.job_name

    metrics_client = MetricsClient(cluster)

    context.log.info(f"Starting reconciliation for team_id: {team_id}")

    total_persons_processed = 0
    total_persons_updated = 0
    total_persons_skipped = 0

    try:
        start_time = time.time()

        # Query ClickHouse for all persons with property updates in this team
        person_property_updates = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=config.bug_window_start,
            bug_window_end=config.bug_window_end,
        )

        if not person_property_updates:
            context.log.info(f"No persons to reconcile for team_id={team_id}")
            return {
                "team_id": team_id,
                "persons_processed": 0,
                "persons_updated": 0,
                "persons_skipped": 0,
            }

        context.log.info(f"Processing {len(person_property_updates)} persons for team_id={team_id}")

        with database.cursor() as cursor:
            cursor.execute("SET application_name = 'person_property_reconciliation'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '30min'")
            cursor.execute("SET synchronous_commit = off")

            # Process each person with version check and retry
            persons_to_publish = []
            for person_updates in person_property_updates:
                success, person_data = update_person_with_version_check(
                    cursor=cursor,
                    team_id=team_id,
                    person_uuid=person_updates.person_id,
                    property_updates=person_updates.updates,
                    dry_run=config.dry_run,
                )

                if not success:
                    context.log.warning(f"Failed to update person after retries: {person_updates.person_id}")
                    total_persons_skipped += 1
                elif person_data:
                    # Successfully updated - queue for Kafka publishing
                    persons_to_publish.append(person_data)
                    total_persons_updated += 1
                else:
                    # No changes needed
                    total_persons_skipped += 1

                total_persons_processed += 1

            # Publish to Kafka
            if persons_to_publish and not config.dry_run:
                for person_data in persons_to_publish:
                    try:
                        publish_person_to_kafka(person_data)
                    except Exception as kafka_error:
                        context.log.warning(
                            f"Failed to publish person to Kafka: {person_data['id']}, error: {kafka_error}"
                        )
                context.log.info(f"Applied {len(persons_to_publish)} updates for team_id={team_id} (PG + Kafka)")
            elif persons_to_publish and config.dry_run:
                context.log.info(f"[DRY RUN] Would apply {len(persons_to_publish)} updates for team_id={team_id}")

        # Track metrics
        duration = time.time() - start_time
        try:
            metrics_client.increment(
                "person_property_reconciliation_persons_processed_total",
                labels={"job_name": job_name, "chunk_id": chunk_id},
                value=float(total_persons_processed),
            ).result()
            metrics_client.increment(
                "person_property_reconciliation_duration_seconds_total",
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
                "person_property_reconciliation_error",
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
                "persons_processed_before_failure": dagster.MetadataValue.int(total_persons_processed),
            },
        ) from e

    context.log.info(
        f"Completed team_id={team_id}: processed={total_persons_processed}, updated={total_persons_updated}, skipped={total_persons_skipped}"
    )

    try:
        metrics_client.increment(
            "person_property_reconciliation_persons_updated_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_persons_updated),
        ).result()
        metrics_client.increment(
            "person_property_reconciliation_persons_skipped_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_persons_skipped),
        ).result()
    except Exception:
        pass

    context.add_output_metadata(
        {
            "team_id": dagster.MetadataValue.int(team_id),
            "persons_processed": dagster.MetadataValue.int(total_persons_processed),
            "persons_updated": dagster.MetadataValue.int(total_persons_updated),
            "persons_skipped": dagster.MetadataValue.int(total_persons_skipped),
        }
    )

    return {
        "team_id": team_id,
        "persons_processed": total_persons_processed,
        "persons_updated": total_persons_updated,
        "persons_skipped": total_persons_skipped,
    }


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": MAX_CONCURRENT_TEAMS}),
)
def person_property_reconciliation_job():
    """
    One-time job to reconcile person properties that were missed due to the
    ASSERT_VERSION bug. Processes teams in parallel with capped concurrency.
    """
    team_ids = get_team_ids_to_reconcile()
    chunks = create_team_chunks(team_ids)
    chunks.map(reconcile_team_chunk)
