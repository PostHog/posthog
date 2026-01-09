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
    team_ids: list[int] | None = None  # Optional: filter to specific teams
    bug_window_end: str | None = None  # Optional: required if team_ids not supplied
    dry_run: bool = False  # Log changes without applying
    backup_enabled: bool = True  # Store before/after state in backup table
    batch_size: int = 100  # Commit Postgres transaction every N persons (0 = single commit at end)


@dataclass
class PropertyValue:
    """A property value with its timestamp."""

    timestamp: datetime  # UTC datetime
    value: Any | None  # None for unset operations


@dataclass
class PersonPropertyDiffs:
    """Property diffs for a single person, organized by operation type."""

    person_id: str
    set_updates: dict[str, PropertyValue]  # key -> PropertyValue
    set_once_updates: dict[str, PropertyValue]  # key -> PropertyValue
    unset_updates: dict[str, PropertyValue]  # key -> PropertyValue (value is always None)


class SkipReason:
    """Reasons why a person update was skipped."""

    SUCCESS = "success"  # Not skipped - successfully updated
    NO_CHANGES = "no_changes"  # No changes needed after reconciliation
    NOT_FOUND = "not_found"  # Person not found in Postgres
    VERSION_CONFLICT = "version_conflict"  # Version mismatch after max retries


# Properties that should NOT trigger a person update on their own.
# These change frequently but aren't valuable enough to update the person record for.
# Keep in sync with: nodejs/src/worker/ingestion/persons/person-property-utils.ts
FILTERED_PERSON_UPDATE_PROPERTIES = frozenset(
    [
        # URL/navigation properties - change on every page view
        "$current_url",
        "$pathname",
        "$referring_domain",
        "$referrer",
        # Screen/viewport dimensions - can change on window resize
        "$screen_height",
        "$screen_width",
        "$viewport_height",
        "$viewport_width",
        # Browser/device properties - change less frequently but still filtered
        "$browser",
        "$browser_version",
        "$device_type",
        "$raw_user_agent",
        "$os",
        "$os_name",
        "$os_version",
        # GeoIP properties - filtered because they change frequently
        # Note: $geoip_country_name and $geoip_city_name DO trigger updates (not listed here)
        "$geoip_postal_code",
        "$geoip_time_zone",
        "$geoip_latitude",
        "$geoip_longitude",
        "$geoip_accuracy_radius",
        "$geoip_subdivision_1_code",
        "$geoip_subdivision_1_name",
        "$geoip_subdivision_2_code",
        "$geoip_subdivision_2_name",
        "$geoip_subdivision_3_code",
        "$geoip_subdivision_3_name",
        "$geoip_city_confidence",
        "$geoip_country_confidence",
        "$geoip_postal_code_confidence",
        "$geoip_subdivision_1_confidence",
        "$geoip_subdivision_2_confidence",
    ]
)


def ensure_utc_datetime(ts: datetime) -> datetime:
    """Ensure timestamp is a UTC-aware datetime."""
    from datetime import UTC

    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def get_person_property_updates_from_clickhouse(
    team_id: int,
    bug_window_start: str,
) -> list[PersonPropertyDiffs]:
    """
    Query ClickHouse to get property updates per person that differ from current state.

    This query:
    1. Joins events with person_distinct_id_overrides to resolve merged persons
    2. Extracts $set (argMax for latest), $set_once (argMin for first), and $unset properties
    3. Compares with current person properties in ClickHouse
    4. Returns only persons where properties differ, are missing, or need removal

    Returns:
        List of PersonPropertyDiffs, each containing 3 maps (set, set_once, unset) keyed by property key
    """
    query = """
    -- CTE 1: Extract and filter properties from events, grouped by (person_id, distinct_id)
    -- Uses e.person_id directly first (no overrides join yet for efficiency)
    WITH event_properties_all AS (
        SELECT
            person_id,
            distinct_id,
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
                distinct_id,
                groupArray(tuple(key, value, kv_timestamp, prop_type)) AS grouped_props
            FROM (
                SELECT
                    e.person_id AS person_id,
                    e.distinct_id AS distinct_id,
                    kv_tuple.2 AS key,
                    kv_tuple.1 AS prop_type,
                    -- $set: newest event wins, $set_once: first event wins, $unset: newest event wins
                    if(kv_tuple.1 = 'set',
                        argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''),
                        argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
                    ) AS value,
                    if(kv_tuple.1 = 'set_once', min(e.timestamp), max(e.timestamp)) AS kv_timestamp
                FROM events e
                ARRAY JOIN
                    arrayConcat(
                        arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null' AND x.2 NOT IN %(filtered_properties)s,
                            arrayMap(x -> tuple('set', x.1, toString(x.2)),
                                arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set'))
                            )
                        ),
                        arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null' AND x.2 NOT IN %(filtered_properties)s,
                            arrayMap(x -> tuple('set_once', x.1, toString(x.2)),
                                arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set_once'))
                            )
                        ),
                        arrayFilter(x -> x.2 NOT IN %(filtered_properties)s,
                            arrayMap(x -> tuple('unset', JSON_VALUE(x, '$'), ''),
                                JSONExtractArrayRaw(e.properties, '$unset')
                            )
                        )
                    ) AS kv_tuple
                WHERE e.team_id = %(team_id)s
                  AND e.timestamp > %(bug_window_start)s
                  AND e.timestamp < now()
                  AND (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '' OR notEmpty(JSONExtractArrayRaw(e.properties, '$unset')))
                GROUP BY e.person_id, e.distinct_id, kv_tuple.2, kv_tuple.1
            )
            GROUP BY person_id, distinct_id
        )
    ),
    -- CTE 2: Filter to only persons with non-empty property sets
    event_properties_raw AS (
        SELECT *
        FROM event_properties_all
        WHERE length(set_keys) > 0 OR length(set_once_keys) > 0 OR length(unset_keys) > 0
    ),
    -- CTE 3: Get overrides only for distinct_ids that have properties
    overrides AS (
        SELECT
            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
            person_distinct_id_overrides.distinct_id AS distinct_id
        FROM person_distinct_id_overrides
        WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
          AND person_distinct_id_overrides.distinct_id IN (SELECT distinct_id FROM event_properties_raw)
        GROUP BY person_distinct_id_overrides.distinct_id
        HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
    ),
    -- CTE 3: Apply overrides to get final person_id and re-aggregate
    event_properties AS (
        SELECT
            if(notEmpty(o.distinct_id), o.person_id, ep.person_id) AS person_id,
            arrayConcat(groupArray(ep.set_keys)) AS set_keys_nested,
            arrayConcat(groupArray(ep.set_values)) AS set_values_nested,
            arrayConcat(groupArray(ep.set_timestamps)) AS set_timestamps_nested,
            arrayConcat(groupArray(ep.set_once_keys)) AS set_once_keys_nested,
            arrayConcat(groupArray(ep.set_once_values)) AS set_once_values_nested,
            arrayConcat(groupArray(ep.set_once_timestamps)) AS set_once_timestamps_nested,
            arrayConcat(groupArray(ep.unset_keys)) AS unset_keys_nested,
            arrayConcat(groupArray(ep.unset_timestamps)) AS unset_timestamps_nested
        FROM event_properties_raw ep
        LEFT OUTER JOIN overrides o ON ep.distinct_id = o.distinct_id
        GROUP BY if(notEmpty(o.distinct_id), o.person_id, ep.person_id)
    ),
    -- CTE 4: Flatten nested arrays from re-aggregation
    event_properties_flat AS (
        SELECT
            person_id,
            arrayFlatten(set_keys_nested) AS set_keys,
            arrayFlatten(set_values_nested) AS set_values,
            arrayFlatten(set_timestamps_nested) AS set_timestamps,
            arrayFlatten(set_once_keys_nested) AS set_once_keys,
            arrayFlatten(set_once_values_nested) AS set_once_values,
            arrayFlatten(set_once_timestamps_nested) AS set_once_timestamps,
            arrayFlatten(unset_keys_nested) AS unset_keys,
            arrayFlatten(unset_timestamps_nested) AS unset_timestamps
        FROM event_properties
    ),
    -- CTE 5: Get person properties only for affected persons
    person_props AS (
        SELECT
            id,
            argMax(properties, version) as person_properties
        FROM person
        WHERE team_id = %(team_id)s
          AND id IN (SELECT person_id FROM event_properties_flat)
        GROUP BY id
        HAVING argMax(is_deleted, version) = 0
    )
    SELECT
        ep.person_id,
        -- For $set: only include properties where the key exists in person properties AND the value differs
        arrayMap(i -> (ep.set_keys[i], ep.set_values[i], ep.set_timestamps[i]), arrayFilter(
            i -> (
                indexOf(keys2, ep.set_keys[i]) > 0
                AND ep.set_values[i] != vals2[indexOf(keys2, ep.set_keys[i])]
            ),
            arrayEnumerate(ep.set_keys)
        )) AS set_diff,
        -- For $set_once: only include properties where the key does NOT exist in person properties
        arrayFilter(
            kv -> indexOf(keys2, kv.1) = 0,
            arrayMap(i -> (ep.set_once_keys[i], ep.set_once_values[i], ep.set_once_timestamps[i]), arrayEnumerate(ep.set_once_keys))
        ) AS set_once_diff,
        -- For $unset: only include keys that EXIST in person properties (need removal)
        arrayFilter(
            kv -> indexOf(keys2, kv.1) > 0,
            arrayMap(i -> (ep.unset_keys[i], ep.unset_timestamps[i]), arrayEnumerate(ep.unset_keys))
        ) AS unset_diff
    FROM event_properties_flat ep
    INNER JOIN (
        SELECT
            id,
            person_properties,
            arrayMap(x -> x.1, JSONExtractKeysAndValuesRaw(person_properties)) AS keys2,
            arrayMap(x -> toString(x.2), JSONExtractKeysAndValuesRaw(person_properties)) AS vals2
        FROM person_props
    ) AS p ON p.id = ep.person_id
    WHERE length(set_diff) > 0 OR length(set_once_diff) > 0 OR length(unset_diff) > 0
    ORDER BY ep.person_id
    SETTINGS
        readonly=2,
        max_execution_time=1200,
        allow_experimental_object_type=1,
        format_csv_allow_double_quotes=0,
        max_ast_elements=4000000,
        max_expanded_ast_elements=4000000,
        allow_experimental_analyzer=1,
        transform_null_in=1,
        optimize_min_equality_disjunction_chain_length=4294967295,
        allow_experimental_join_condition=1,
        use_hive_partitioning=0
    """

    params = {
        "team_id": team_id,
        "bug_window_start": bug_window_start,
        "filtered_properties": tuple(FILTERED_PERSON_UPDATE_PROPERTIES),
    }

    rows = sync_execute(query, params)

    results: list[PersonPropertyDiffs] = []
    for row in rows:
        person_id, set_diff, set_once_diff, unset_diff = row

        set_updates: dict[str, PropertyValue] = {}
        for key, value, timestamp in set_diff:
            set_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=json.loads(value),
            )

        set_once_updates: dict[str, PropertyValue] = {}
        for key, value, timestamp in set_once_diff:
            set_once_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=json.loads(value),
            )

        unset_updates: dict[str, PropertyValue] = {}
        for key, timestamp in unset_diff:
            unset_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=None,
            )

        if set_updates or set_once_updates or unset_updates:
            results.append(
                PersonPropertyDiffs(
                    person_id=str(person_id),
                    set_updates=set_updates,
                    set_once_updates=set_once_updates,
                    unset_updates=unset_updates,
                )
            )

    return results


def filter_event_person_properties(
    person_diffs: list[PersonPropertyDiffs],
) -> list[PersonPropertyDiffs]:
    """
    Filter conflicting set/unset operations by timestamp.

    For each key that appears in both set_updates and unset_updates:
    - If set timestamp > unset timestamp: keep set, remove unset
    - If unset timestamp >= set timestamp: keep unset, remove set

    Returns filtered PersonPropertyDiffs with conflicts resolved.
    """
    results: list[PersonPropertyDiffs] = []

    for diffs in person_diffs:
        # Copy the maps so we don't mutate the input
        set_updates = dict(diffs.set_updates)
        set_once_updates = dict(diffs.set_once_updates)
        unset_updates = dict(diffs.unset_updates)

        # Find keys that exist in both maps
        # Use original unset keys for iteration so deletions in first loop don't affect second loop
        original_unset_keys = list(diffs.unset_updates.keys())

        for key in original_unset_keys:
            if key in set_updates:
                set_ts = set_updates[key].timestamp
                unset_ts = diffs.unset_updates[key].timestamp

                if set_ts > unset_ts:
                    # set is more recent - remove unset
                    del unset_updates[key]
                else:
                    # unset is more recent or equal - remove set
                    del set_updates[key]

        # Filter set_once vs unset conflicts
        for key in original_unset_keys:
            if key in set_once_updates:
                set_once_ts = set_once_updates[key].timestamp
                unset_ts = diffs.unset_updates[key].timestamp

                if set_once_ts > unset_ts:
                    # Only delete if not already removed by set loop
                    if key in unset_updates:
                        del unset_updates[key]
                else:
                    del set_once_updates[key]

        results.append(
            PersonPropertyDiffs(
                person_id=diffs.person_id,
                set_updates=set_updates,
                set_once_updates=set_once_updates,
                unset_updates=unset_updates,
            )
        )

    return results


def reconcile_person_properties(
    person: dict,
    person_property_diffs: PersonPropertyDiffs,
) -> dict | None:
    """
    Compute updated properties by comparing ClickHouse updates with current Postgres state.

    The CH query pre-filters to only return:
    - $set properties where the CH value differs from current person state
    - $set_once properties that are missing from current person state
    - $unset properties that exist in current person state

    Args:
        person: From Postgres with uuid, properties, properties_last_updated_at, properties_last_operation
        person_property_diffs: Property diffs from ClickHouse

    Returns:
        Dict with updated properties/metadata if changes needed, None otherwise.
    """
    properties = dict(person["properties"] or {})
    properties_last_updated_at = dict(person["properties_last_updated_at"] or {})
    properties_last_operation = dict(person["properties_last_operation"] or {})

    changed = False

    # 1. set_once: only update if key not in properties
    for key, pv in person_property_diffs.set_once_updates.items():
        if key not in properties:
            properties[key] = pv.value
            properties_last_updated_at[key] = pv.timestamp.isoformat()
            properties_last_operation[key] = "set_once"
            changed = True

    # 2. set: always update
    for key, pv in person_property_diffs.set_updates.items():
        properties[key] = pv.value
        properties_last_updated_at[key] = pv.timestamp.isoformat()
        properties_last_operation[key] = "set"
        changed = True

    # 3. unset: delete from all maps
    for key in person_property_diffs.unset_updates.keys():
        if key in properties:
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
        "id",
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
            id,
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
    person_property_diffs: PersonPropertyDiffs,
    computed_update: dict,
    new_version: int,
) -> bool:
    """
    Store person state in backup table with both before and after states.
    Called after computing the update but before applying it.
    Returns True if backup was successful, False otherwise.
    """
    pending_operations = []
    for key, pv in person_property_diffs.set_updates.items():
        pending_operations.append(
            {"key": key, "value": pv.value, "timestamp": pv.timestamp.isoformat(), "operation": "set"}
        )
    for key, pv in person_property_diffs.set_once_updates.items():
        pending_operations.append(
            {"key": key, "value": pv.value, "timestamp": pv.timestamp.isoformat(), "operation": "set_once"}
        )
    for key, pv in person_property_diffs.unset_updates.items():
        pending_operations.append(
            {"key": key, "value": None, "timestamp": pv.timestamp.isoformat(), "operation": "unset"}
        )

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
    person_property_diffs: PersonPropertyDiffs,
    dry_run: bool = False,
    backup_enabled: bool = True,
    max_retries: int = 3,
) -> tuple[bool, dict | None, bool, str]:
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
        person_property_diffs: Property diffs from ClickHouse
        dry_run: If True, don't actually write the UPDATE
        backup_enabled: If True, store before/after state in backup table
        max_retries: Maximum retry attempts on version mismatch

    Returns:
        Tuple of (success: bool, updated_person_data: dict | None, backup_created: bool, skip_reason: str)
        updated_person_data contains the final state for Kafka publishing
        backup_created indicates if a backup row was inserted
        skip_reason indicates why the person was skipped (see SkipReason class)
    """
    for _attempt in range(max_retries):
        # Fetch current person state
        person = fetch_person_from_postgres(cursor, team_id, person_uuid)
        if not person:
            return False, None, False, SkipReason.NOT_FOUND

        current_version = person.get("version") or 0

        # Compute updates
        update = reconcile_person_properties(person, person_property_diffs)
        if not update:
            # No changes needed
            return True, None, False, SkipReason.NO_CHANGES

        # Backup before and after state for audit/rollback
        backup_created = False
        if backup_enabled:
            backup_person_with_computed_state(
                cursor, job_id, team_id, person, person_property_diffs, update, current_version + 1
            )
            backup_created = True

        if dry_run:
            return True, None, backup_created, SkipReason.SUCCESS

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
                SkipReason.SUCCESS,
            )

        # Version mismatch - retry with fresh data
        # (loop will re-fetch person)

    # Exhausted retries
    return False, None, False, SkipReason.VERSION_CONFLICT


@dataclass
class BatchProcessingResult:
    """Result of processing persons in batches."""

    total_processed: int
    total_updated: int
    total_skipped: int
    total_commits: int


def process_persons_in_batches(
    person_property_diffs: list[PersonPropertyDiffs],
    cursor: Any,
    job_id: str,
    team_id: int,
    batch_size: int,
    dry_run: bool,
    backup_enabled: bool,
    commit_fn: Any,  # Callable to commit transaction
    on_person_updated: Any = None,  # Optional callback for Kafka publishing etc
    on_batch_committed: Any = None,  # Optional callback after each batch commit
    logger: Any = None,  # Optional logger for logging skipped persons
) -> BatchProcessingResult:
    """
    Process person property updates in batches with configurable commit frequency.

    This function is separated from the Dagster op for testability.

    Args:
        person_property_diffs: List of persons with their property diffs
        cursor: Database cursor (already open in transaction)
        job_id: Job identifier for backups
        team_id: Team being processed
        batch_size: Number of persons per batch (0 = all in one batch)
        dry_run: If True, don't actually apply changes
        backup_enabled: If True, create backup rows
        commit_fn: Function to call for committing the transaction
        on_person_updated: Optional callback(person_data) when a person is updated
        on_batch_committed: Optional callback(batch_num, batch_persons) after each commit
        logger: Optional logger for logging skipped persons (e.g., context.log from Dagster)

    Returns:
        BatchProcessingResult with counts
    """
    if not person_property_diffs:
        return BatchProcessingResult(
            total_processed=0,
            total_updated=0,
            total_skipped=0,
            total_commits=0,
        )

    # Determine effective batch size
    effective_batch_size = batch_size if batch_size > 0 else len(person_property_diffs)

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

    for i, person_diffs in enumerate(person_property_diffs):
        success, person_data, backup_created, skip_reason = update_person_with_version_check(
            cursor=cursor,
            job_id=job_id,
            team_id=team_id,
            person_uuid=person_diffs.person_id,
            person_property_diffs=person_diffs,
            dry_run=dry_run,
            backup_enabled=backup_enabled,
        )

        if backup_created:
            batch_has_backups = True

        if not success:
            total_skipped += 1
            if logger:
                logger.warning(f"Skipped person uuid={person_diffs.person_id} team_id={team_id} reason={skip_reason}")
        elif person_data:
            batch_persons_to_publish.append(person_data)
            total_updated += 1
            if on_person_updated:
                on_person_updated(person_data)
        else:
            # No changes needed (success=True but person_data=None)
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

    if not config.bug_window_end:
        raise dagster.Failure(
            description="Either team_ids or bug_window_end must be provided",
            metadata={
                "bug_window_start": dagster.MetadataValue.text(config.bug_window_start),
            },
        )

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

    context.log.info(
        f"Starting reconciliation for team_id: {team_id}, "
        f"bug_window_start: {config.bug_window_start}, "
        f"dry_run: {config.dry_run}"
    )

    total_persons_processed = 0
    total_persons_updated = 0
    total_persons_skipped = 0

    try:
        start_time = time.time()

        # Query ClickHouse for all persons with property updates in this team
        person_property_diffs = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=config.bug_window_start,
        )

        # Filter conflicting set/unset operations
        person_property_diffs = filter_event_person_properties(person_property_diffs)

        if not person_property_diffs:
            context.log.info(f"No persons to reconcile for team_id={team_id}")
            return {
                "team_id": team_id,
                "persons_processed": 0,
                "persons_updated": 0,
                "persons_skipped": 0,
            }

        context.log.info(f"Processing {len(person_property_diffs)} persons for team_id={team_id}")

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
                person_property_diffs=person_property_diffs,
                cursor=cursor,
                job_id=run_id,
                team_id=team_id,
                batch_size=config.batch_size,
                dry_run=config.dry_run,
                backup_enabled=config.backup_enabled,
                commit_fn=persons_database.commit,
                on_batch_committed=on_batch_committed,
                logger=context.log,
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
