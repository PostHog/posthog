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

from django.conf import settings

import dagster
import psycopg2
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.kafka_client.client import _KafkaProducer
from posthog.kafka_client.topics import KAFKA_PERSON

# Use in_process_executor locally (k8s_job_executor doesn't work outside k8s)
executor_def = dagster.in_process_executor if settings.DEBUG else k8s_job_executor


class PersonPropertyReconciliationConfig(dagster.Config):
    """Configuration for the person property reconciliation job."""

    bug_window_start: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS" (assumed UTC)
    bug_window_end: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS" (assumed UTC)
    team_ids: list[int] | None = None  # Optional: filter to specific teams
    dry_run: bool = False  # Log changes without applying
    backup_enabled: bool = True  # Store before/after state in backup table
    batch_size: int = 100  # Commit Postgres transaction every N persons (0 = single commit at end)


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


def parse_datetime(dt_str: str, person_id: str, property_key: str) -> datetime:
    """Parse an ISO format datetime string, assuming UTC if no timezone."""
    from datetime import UTC

    import structlog

    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        structlog.get_logger(__name__).warning(
            "naive_datetime_assumed_utc",
            datetime_str=dt_str,
            person_id=person_id,
            property_key=property_key,
        )
        dt = dt.replace(tzinfo=UTC)
    return dt


def get_person_property_updates_from_clickhouse(
    team_id: int,
    bug_window_start: str,
    bug_window_end: str,
) -> list[PersonPropertyUpdates]:
    """
    Query ClickHouse to get property updates per person that differ from current state.

    This query:
    1. Joins events with person_distinct_id_overrides to resolve merged persons
    2. Extracts $set (argMax for latest), $set_once (argMin for first), and $unset properties
    3. Compares with current person properties in ClickHouse
    4. Returns only persons where properties differ, are missing, or need removal

    Returns:
        set_diff: Array of (key, value, timestamp) tuples for $set properties that differ
        set_once_diff: Array of (key, value, timestamp) tuples for $set_once properties missing
        unset_diff: Array of (key, timestamp) tuples for $unset properties that exist
    """
    query = """
    SELECT
        with_person_props.person_id,
        -- For $set: only include properties where the key exists in person properties AND the value differs
        -- Use JSON_VALUE to parse raw JSON strings for proper comparison (e.g., '"value"' -> 'value')
        arrayMap(i -> (set_keys[i], set_values[i], set_timestamps[i]), arrayFilter(
            i -> (
                indexOf(keys2, set_keys[i]) > 0
                AND JSON_VALUE(set_values[i], '$') != vals2[indexOf(keys2, set_keys[i])]
            ),
            arrayEnumerate(set_keys)
        )) AS set_diff,
        -- For $set_once: only include properties where the key does NOT exist in person properties
        arrayFilter(
            kv -> indexOf(keys2, kv.1) = 0,
            arrayMap(i -> (set_once_keys[i], set_once_values[i], set_once_timestamps[i]), arrayEnumerate(set_once_keys))
        ) AS set_once_diff,
        -- For $unset: only include keys that EXIST in person properties (need removal)
        arrayFilter(
            kv -> indexOf(keys2, kv.1) > 0,
            arrayMap(i -> (unset_keys[i], unset_timestamps[i]), arrayEnumerate(unset_keys))
        ) AS unset_diff
    FROM (
        SELECT
            merged.person_id,
            merged.set_keys,
            merged.set_values,
            merged.set_timestamps,
            merged.set_once_keys,
            merged.set_once_values,
            merged.set_once_timestamps,
            merged.unset_keys,
            merged.unset_timestamps,
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
                arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_timestamps,
                arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'unset', grouped_props)) AS unset_keys,
                arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'unset', grouped_props)) AS unset_timestamps
            FROM (
                SELECT
                    person_id,
                    groupArray(tuple(key, value, kv_timestamp, prop_type)) AS grouped_props
                FROM (
                    SELECT
                        if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id) AS person_id,
                        kv_tuple.2 AS key,
                        kv_tuple.1 AS prop_type,
                        -- $set: newest event wins, $set_once: first event wins, $unset: newest event wins
                        -- Filter out null/empty values with argMaxIf/argMinIf
                        if(kv_tuple.1 = 'set',
                            argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''),
                            argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
                        ) AS value,
                        if(kv_tuple.1 = 'set_once', min(e.timestamp), max(e.timestamp)) AS kv_timestamp
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
                    -- Extract $set, $set_once, and $unset properties, filtering out null/empty values
                    ARRAY JOIN
                        arrayConcat(
                            arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
                                arrayMap(x -> tuple('set', x.1, toString(x.2)),
                                    arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set'))
                                )
                            ),
                            arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null',
                                arrayMap(x -> tuple('set_once', x.1, toString(x.2)),
                                    arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set_once'))
                                )
                            ),
                            -- $unset is an array of keys, not key-value pairs
                            -- Parse keys with JSON_VALUE to get plain strings (consistent with $set/$set_once)
                            arrayMap(x -> tuple('unset', JSON_VALUE(x, '$'), ''),
                                JSONExtractArrayRaw(e.properties, '$unset')
                            )
                        ) AS kv_tuple
                    WHERE e.team_id = %(team_id)s
                      AND e.timestamp > %(bug_window_start)s
                      AND e.timestamp < %(bug_window_end)s
                      AND (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '' OR notEmpty(JSONExtractArrayRaw(e.properties, '$unset')))
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
            -- Filter out deleted persons (latest version has is_deleted=1)
            HAVING argMax(is_deleted, version) = 0
        ) AS p ON p.id = merged.person_id
    ) AS with_person_props
    WHERE length(set_diff) > 0 OR length(set_once_diff) > 0 OR length(unset_diff) > 0
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
        person_id, set_diff, set_once_diff, unset_diff = row

        updates: list[PropertyUpdate] = []

        # Add differing $set properties (tuples of key, value, timestamp)
        for key, value, timestamp in set_diff:
            updates.append(
                PropertyUpdate(
                    key=key,
                    value=json.loads(value),  # Parse raw JSON: strip quotes from strings, convert types
                    timestamp=timestamp,
                    operation="set",
                )
            )

        # Add missing $set_once properties (tuples of key, value, timestamp)
        for key, value, timestamp in set_once_diff:
            updates.append(
                PropertyUpdate(
                    key=key,
                    value=json.loads(value),  # Parse raw JSON: strip quotes from strings, convert types
                    timestamp=timestamp,
                    operation="set_once",
                )
            )

        # Add $unset operations (tuples of key, timestamp - no value)
        # Keys are already parsed in the query with JSON_VALUE (consistent with $set/$set_once)
        for key, timestamp in unset_diff:
            updates.append(
                PropertyUpdate(
                    key=key,
                    value=None,
                    timestamp=timestamp,
                    operation="unset",
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
    - $unset properties that exist in current person state

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
            # set_once: only add if property doesn't already exist in PG
            if key not in properties:
                properties[key] = value
                properties_last_updated_at[key] = event_ts_str
                properties_last_operation[key] = "set_once"
                changed = True
        elif operation == "set":
            # set: create or update property if CH timestamp is newer (or no existing timestamp)
            if existing_ts_str is None or event_ts > parse_datetime(existing_ts_str, person["uuid"], key):
                properties[key] = value
                properties_last_updated_at[key] = event_ts_str
                properties_last_operation[key] = "set"
                changed = True
        elif operation == "unset":
            # unset: remove property if it exists AND CH timestamp is newer
            if key in properties:
                if existing_ts_str is None or event_ts > parse_datetime(existing_ts_str, person["uuid"], key):
                    del properties[key]
                    if key in properties_last_updated_at:
                        del properties_last_updated_at[key]
                    if key in properties_last_operation:
                        del properties_last_operation[key]
                    changed = True

    if changed:
        return {
            "properties": properties,
            "properties_last_updated_at": properties_last_updated_at,
            "properties_last_operation": properties_last_operation,
        }
    return None


def publish_person_to_kafka(person_data: dict, producer: _KafkaProducer) -> None:
    """
    Publish a person update to the Kafka topic for ClickHouse ingestion.

    Args:
        person_data: Dict with id, team_id, properties, is_identified, is_deleted, created_at, version
        producer: Kafka producer instance (injected resource)
    """
    from django.utils.timezone import now

    # Format data for Kafka/ClickHouse
    created_at = person_data.get("created_at")
    if created_at is not None and hasattr(created_at, "strftime"):
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
    }

    producer.produce(topic=KAFKA_PERSON, data=kafka_data)


def fetch_person_from_postgres(cursor, team_id: int, person_uuid: str) -> dict | None:
    """Fetch a single person record from Postgres.

    Works with both RealDictCursor (returns dict rows with auto-parsed JSONB)
    and regular cursor (returns tuple rows with JSONB as strings).
    """
    columns = [
        "uuid",
        "properties",
        "properties_last_updated_at",
        "properties_last_operation",
        "version",
        "is_identified",
        "created_at",
    ]
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
    if row is None:
        return None
    # Handle both dict rows (RealDictCursor) and tuple rows (regular cursor)
    if isinstance(row, dict):
        result = dict(row)
    else:
        result = dict(zip(columns, row))

    # Parse JSONB columns if they're strings (Django cursor doesn't auto-parse)
    for json_col in ["properties", "properties_last_updated_at", "properties_last_operation"]:
        if isinstance(result.get(json_col), str):
            result[json_col] = json.loads(result[json_col])

    return result


def backup_person_with_computed_state(
    cursor,
    job_id: str,
    team_id: int,
    person: dict,
    property_updates: list[PropertyUpdate],
    computed_update: dict,
    new_version: int,
) -> bool:
    """
    Store person state in backup table with both before and after states.
    Called after computing the update but before applying it.
    Returns True if backup was successful, False otherwise.
    """
    pending_operations = [
        {
            "key": u.key,
            "value": u.value,
            "timestamp": u.timestamp.isoformat(),
            "operation": u.operation,
        }
        for u in property_updates
    ]

    cursor.execute(
        """
        INSERT INTO posthog_person_reconciliation_backup (
            job_id, team_id, person_id, uuid,
            properties, properties_last_updated_at, properties_last_operation,
            version, is_identified, created_at, is_user_id,
            pending_operations,
            properties_after, properties_last_updated_at_after,
            properties_last_operation_after, version_after
        ) VALUES (
            %s, %s, %s, %s::uuid,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (job_id, team_id, person_id) DO NOTHING
        """,
        (
            job_id,
            team_id,
            person["id"],
            str(person["uuid"]),
            json.dumps(person.get("properties", {})),
            json.dumps(person.get("properties_last_updated_at")),
            json.dumps(person.get("properties_last_operation")),
            person.get("version"),
            person.get("is_identified", False),
            person.get("created_at"),
            person.get("is_user_id"),
            json.dumps(pending_operations),
            json.dumps(computed_update["properties"]),
            json.dumps(computed_update["properties_last_updated_at"]),
            json.dumps(computed_update["properties_last_operation"]),
            new_version,
        ),
    )
    return True


def update_person_with_version_check(
    cursor,
    job_id: str,
    team_id: int,
    person_uuid: str,
    property_updates: list[PropertyUpdate],
    dry_run: bool = False,
    backup_enabled: bool = True,
    max_retries: int = 3,
) -> tuple[bool, dict | None, bool]:
    """
    Update a person's properties with optimistic locking.

    Fetches the person, computes updates, and writes with version check.
    If version changed (concurrent modification), re-fetches and retries.
    Optionally backs up the before/after state for audit purposes.

    Args:
        cursor: Database cursor
        job_id: Dagster run ID for backup tracking
        team_id: Team ID
        person_uuid: Person UUID
        property_updates: Property updates from ClickHouse
        dry_run: If True, don't actually write the UPDATE
        backup_enabled: If True, store before/after state in backup table
        max_retries: Maximum retry attempts on version mismatch

    Returns:
        Tuple of (success: bool, updated_person_data: dict | None, backup_created: bool)
        updated_person_data contains the final state for Kafka publishing
        backup_created indicates if a backup row was inserted
    """
    for _attempt in range(max_retries):
        # Fetch current person state
        person = fetch_person_from_postgres(cursor, team_id, person_uuid)
        if not person:
            return False, None, False

        current_version = person.get("version") or 0

        # Compute updates
        update = reconcile_person_properties(person, property_updates)
        if not update:
            # No changes needed
            return True, None, False

        # Backup before and after state for audit/rollback
        backup_created = False
        if backup_enabled:
            backup_person_with_computed_state(
                cursor, job_id, team_id, person, property_updates, update, current_version + 1
            )
            backup_created = True

        if dry_run:
            return True, None, backup_created

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
                backup_created,
            )

        # Version mismatch - retry with fresh data
        # (loop will re-fetch person)

    # Exhausted retries
    return False, None, False


@dataclass
class BatchProcessingResult:
    """Result of processing persons in batches."""

    total_processed: int
    total_updated: int
    total_skipped: int
    total_commits: int


def process_persons_in_batches(
    person_property_updates: list[PersonPropertyUpdates],
    cursor: Any,
    job_id: str,
    team_id: int,
    batch_size: int,
    dry_run: bool,
    backup_enabled: bool,
    commit_fn: Any,  # Callable to commit transaction
    on_person_updated: Any = None,  # Optional callback for Kafka publishing etc
    on_batch_committed: Any = None,  # Optional callback after each batch commit
) -> BatchProcessingResult:
    """
    Process person property updates in batches with configurable commit frequency.

    This function is separated from the Dagster op for testability.

    Args:
        person_property_updates: List of persons with their property updates
        cursor: Database cursor (already open in transaction)
        job_id: Job identifier for backups
        team_id: Team being processed
        batch_size: Number of persons per batch (0 = all in one batch)
        dry_run: If True, don't actually apply changes
        backup_enabled: If True, create backup rows
        commit_fn: Function to call for committing the transaction
        on_person_updated: Optional callback(person_data) when a person is updated
        on_batch_committed: Optional callback(batch_num, batch_persons) after each commit

    Returns:
        BatchProcessingResult with counts
    """
    if not person_property_updates:
        return BatchProcessingResult(
            total_processed=0,
            total_updated=0,
            total_skipped=0,
            total_commits=0,
        )

    # Determine effective batch size
    effective_batch_size = batch_size if batch_size > 0 else len(person_property_updates)

    total_processed = 0
    total_updated = 0
    total_skipped = 0
    total_commits = 0

    batch_persons_to_publish: list[dict] = []
    batch_has_backups = False
    batch_num = 1

    def commit_batch() -> None:
        nonlocal total_commits, batch_persons_to_publish, batch_has_backups, batch_num

        if not batch_persons_to_publish and not batch_has_backups:
            return

        # Commit if we have updates OR backups
        should_commit = (batch_persons_to_publish and not dry_run) or batch_has_backups
        if should_commit:
            commit_fn()
            total_commits += 1

        # Notify callback
        if on_batch_committed:
            on_batch_committed(batch_num, batch_persons_to_publish)

        # Reset for next batch
        batch_persons_to_publish = []
        batch_has_backups = False
        batch_num += 1

    for i, person_updates in enumerate(person_property_updates):
        success, person_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id=job_id,
            team_id=team_id,
            person_uuid=person_updates.person_id,
            property_updates=person_updates.updates,
            dry_run=dry_run,
            backup_enabled=backup_enabled,
        )

        if backup_created:
            batch_has_backups = True

        if not success:
            total_skipped += 1
        elif person_data:
            batch_persons_to_publish.append(person_data)
            total_updated += 1
            if on_person_updated:
                on_person_updated(person_data)
        else:
            total_skipped += 1

        total_processed += 1

        # Commit batch if we've reached batch_size
        persons_in_batch = (i % effective_batch_size) + 1
        if persons_in_batch == effective_batch_size:
            commit_batch()

    # Commit final batch (if any remaining)
    if batch_persons_to_publish or batch_has_backups:
        commit_batch()

    return BatchProcessingResult(
        total_processed=total_processed,
        total_updated=total_updated,
        total_skipped=total_skipped,
        total_commits=total_commits,
    )


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
    persons_database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
    kafka_producer: dagster.ResourceParam[_KafkaProducer],
) -> dict[str, Any]:
    """
    Reconcile person properties for all affected persons in a team.
    """
    team_id = chunk
    chunk_id = f"team_{team_id}"
    job_name = context.run.job_name
    run_id = context.run.run_id

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

        # Callback for batch commits - handles Kafka publishing after each batch
        def on_batch_committed(batch_num: int, batch_persons: list[dict]) -> None:
            if batch_persons and not config.dry_run:
                for person_data in batch_persons:
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
                context.log.info(f"Batch {batch_num}: committed {len(batch_persons)} updates for team_id={team_id}")
            elif batch_persons and config.dry_run:
                context.log.info(
                    f"[DRY RUN] Batch {batch_num}: would apply {len(batch_persons)} updates for team_id={team_id}"
                )

        with persons_database.cursor() as cursor:
            cursor.execute("SET application_name = 'person_property_reconciliation'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '30min'")
            cursor.execute("SET synchronous_commit = off")

            # Process persons in batches using the helper function
            result = process_persons_in_batches(
                person_property_updates=person_property_updates,
                cursor=cursor,
                job_id=run_id,
                team_id=team_id,
                batch_size=config.batch_size,
                dry_run=config.dry_run,
                backup_enabled=config.backup_enabled,
                commit_fn=persons_database.commit,
                on_batch_committed=on_batch_committed,
            )

            total_persons_processed = result.total_processed
            total_persons_updated = result.total_updated
            total_persons_skipped = result.total_skipped

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
    executor_def=executor_def,
)
def person_property_reconciliation_job():
    """
    One-time job to reconcile person properties that were missed due to the
    ASSERT_VERSION bug.

    IMPORTANT: This job uses k8s_job_executor which spawns a separate Kubernetes pod
    for each team. Without concurrency limits, this could spin up thousands of pods
    simultaneously. Before running:

    1. Set step concurrency limits in the Dagster UI (Deployment > Configuration)
       or via the run coordinator's concurrency settings
    2. Consider using the `team_ids` config to process a subset of teams first
    3. Monitor cluster resources during execution
    """
    team_ids = get_team_ids_to_reconcile()
    chunks = create_team_chunks(team_ids)
    chunks.map(reconcile_team_chunk)
