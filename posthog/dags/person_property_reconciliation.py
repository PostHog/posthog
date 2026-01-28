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
from datetime import UTC, datetime, timedelta
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
    min_team_id: int | None = None  # Optional: only process teams with id >= this value
    max_team_id: int | None = None  # Optional: only process teams with id <= this value
    exclude_team_ids: list[int] | None = None  # Optional: exclude specific team_ids
    dry_run: bool = False  # Log changes without applying
    backup_enabled: bool = True  # Store before/after state in backup table
    batch_size: int = 100  # Commit Postgres transaction every N persons (0 = single commit at end)
    teams_per_chunk: int = 100  # Number of teams to process per task (reduces task overhead)
    team_ch_props_fetch_window_seconds: int = 0  # 0 = single query; >0 = split into N-second windows


@dataclass
class PropertyValue:
    """A property value with its timestamp."""

    timestamp: datetime  # UTC datetime
    value: Any | None  # None for unset operations


@dataclass
class PersonPropertyDiffs:
    """Property diffs for a single person, organized by operation type."""

    person_id: str
    person_version: int  # Version from CH person table (baseline for conflict detection)
    set_updates: dict[str, PropertyValue]  # key -> PropertyValue
    set_once_updates: dict[str, PropertyValue]  # key -> PropertyValue
    unset_updates: dict[str, PropertyValue]  # key -> PropertyValue (value is always None)


@dataclass
class RawPersonPropertyUpdates:
    """Raw property updates from events, before comparison with person state.

    Used in windowed queries where we aggregate across multiple time windows
    before doing a single comparison against person properties.
    """

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
    -- CTE 1: Get all overrides for the team (no filtering)
    WITH overrides AS (
        SELECT
            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
            person_distinct_id_overrides.distinct_id AS distinct_id
        FROM person_distinct_id_overrides
        WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
        GROUP BY person_distinct_id_overrides.distinct_id
        HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
    ),
    -- CTE 2: Extract properties from events, grouped by RESOLVED person_id (after overrides)
    -- This ensures argMax/argMin aggregates across ALL distinct_ids for the same person
    event_properties_raw AS (
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
                    -- Apply overrides to get resolved person_id
                    if(notEmpty(o.distinct_id), o.person_id, e.person_id) AS person_id,
                    kv_tuple.2 AS key,
                    kv_tuple.1 AS prop_type,
                    -- $set: newest event wins, $set_once: first event wins, $unset: newest event wins
                    if(kv_tuple.1 = 'set',
                        argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''),
                        argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
                    ) AS value,
                    if(kv_tuple.1 = 'set_once', min(e.timestamp), max(e.timestamp)) AS kv_timestamp
                FROM events e
                LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
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
                  AND e.timestamp >= %(bug_window_start)s
                  AND e.timestamp < now()
                  AND (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '' OR notEmpty(JSONExtractArrayRaw(e.properties, '$unset')))
                -- Group by resolved person_id (not distinct_id) so argMax works across all distinct_ids
                GROUP BY if(notEmpty(o.distinct_id), o.person_id, e.person_id), kv_tuple.2, kv_tuple.1
            )
            GROUP BY person_id
        )
    ),
    -- CTE 3: Filter to only persons with non-empty property sets
    event_properties_flat AS (
        SELECT *
        FROM event_properties_raw
        WHERE length(set_keys) > 0 OR length(set_once_keys) > 0 OR length(unset_keys) > 0
    ),
    -- CTE 4: Get person properties and version only for affected persons
    person_props AS (
        SELECT
            id,
            argMax(properties, version) as person_properties,
            argMax(version, version) as person_version
        FROM person
        WHERE team_id = %(team_id)s
          AND id IN (SELECT person_id FROM event_properties_flat)
        GROUP BY id
        HAVING argMax(is_deleted, version) = 0
    )
    SELECT
        ep.person_id,
        p.person_version,
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
            person_version,
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
        person_id, person_version, set_diff, set_once_diff, unset_diff = row

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
                    person_version=int(person_version),
                    set_updates=set_updates,
                    set_once_updates=set_once_updates,
                    unset_updates=unset_updates,
                )
            )

    return results


def get_raw_person_property_updates_from_clickhouse(
    team_id: int,
    bug_window_start: str,
    bug_window_end: str,
) -> list[RawPersonPropertyUpdates]:
    """
    Query ClickHouse to get raw property updates from events WITHOUT comparing to person state.

    This is used for windowed queries where we need to aggregate events across multiple
    time windows before doing a single comparison against person properties.

    Returns raw aggregated event data:
    - $set: argMax for latest value per key
    - $set_once: argMin for first value per key
    - $unset: max timestamp per key

    Args:
        team_id: Team ID to query
        bug_window_start: Start of time window (ClickHouse format: "YYYY-MM-DD HH:MM:SS")
        bug_window_end: End of time window (ClickHouse format: "YYYY-MM-DD HH:MM:SS")

    Returns:
        List of RawPersonPropertyUpdates with aggregated event data (no person comparison)
    """
    query = """
    -- CTE 1: Get all overrides for the team
    WITH overrides AS (
        SELECT
            argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
            person_distinct_id_overrides.distinct_id AS distinct_id
        FROM person_distinct_id_overrides
        WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
        GROUP BY person_distinct_id_overrides.distinct_id
        HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
    ),
    -- CTE 2: Extract and aggregate properties from events
    event_properties_raw AS (
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
                    if(notEmpty(o.distinct_id), o.person_id, e.person_id) AS person_id,
                    kv_tuple.2 AS key,
                    kv_tuple.1 AS prop_type,
                    if(kv_tuple.1 = 'set',
                        argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''),
                        argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
                    ) AS value,
                    if(kv_tuple.1 = 'set_once', min(e.timestamp), max(e.timestamp)) AS kv_timestamp
                FROM events e
                LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
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
                  AND e.timestamp >= %(bug_window_start)s
                  AND e.timestamp < %(bug_window_end)s
                  AND (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '' OR notEmpty(JSONExtractArrayRaw(e.properties, '$unset')))
                GROUP BY if(notEmpty(o.distinct_id), o.person_id, e.person_id), kv_tuple.2, kv_tuple.1
            )
            GROUP BY person_id
        )
    )
    -- Return raw aggregated event data (no person comparison)
    SELECT
        person_id,
        arrayMap(i -> (set_keys[i], set_values[i], set_timestamps[i]), arrayEnumerate(set_keys)) AS set_data,
        arrayMap(i -> (set_once_keys[i], set_once_values[i], set_once_timestamps[i]), arrayEnumerate(set_once_keys)) AS set_once_data,
        arrayMap(i -> (unset_keys[i], unset_timestamps[i]), arrayEnumerate(unset_keys)) AS unset_data
    FROM event_properties_raw
    WHERE length(set_keys) > 0 OR length(set_once_keys) > 0 OR length(unset_keys) > 0
    ORDER BY person_id
    SETTINGS
        readonly=2,
        max_execution_time=600,
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
        "bug_window_end": bug_window_end,
        "filtered_properties": tuple(FILTERED_PERSON_UPDATE_PROPERTIES),
    }

    rows = sync_execute(query, params)

    results: list[RawPersonPropertyUpdates] = []
    for row in rows:
        person_id, set_data, set_once_data, unset_data = row

        set_updates: dict[str, PropertyValue] = {}
        for key, value, timestamp in set_data:
            set_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=json.loads(value),
            )

        set_once_updates: dict[str, PropertyValue] = {}
        for key, value, timestamp in set_once_data:
            set_once_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=json.loads(value),
            )

        unset_updates: dict[str, PropertyValue] = {}
        for key, timestamp in unset_data:
            unset_updates[str(key)] = PropertyValue(
                timestamp=ensure_utc_datetime(timestamp),
                value=None,
            )

        if set_updates or set_once_updates or unset_updates:
            results.append(
                RawPersonPropertyUpdates(
                    person_id=str(person_id),
                    set_updates=set_updates,
                    set_once_updates=set_once_updates,
                    unset_updates=unset_updates,
                )
            )

    return results


def merge_raw_person_property_updates(
    accumulated: dict[str, RawPersonPropertyUpdates],
    new_updates: list[RawPersonPropertyUpdates],
) -> None:
    """
    Merge new raw updates into accumulated dict, keyed by person_id.

    This is used when iterating through time windows to accumulate raw property updates
    across multiple query results BEFORE comparing with person state.

    Merge rules:
    - For $set: newer timestamp replaces older
    - For $set_once: earlier timestamp wins (first-writer-wins semantics)
    - For $unset: newer timestamp replaces older

    Cross-map conflicts (set/set_once vs unset) are resolved downstream by
    filter_event_person_properties after comparison with person state.

    Args:
        accumulated: Dict of person_id -> RawPersonPropertyUpdates to merge into (mutated in place)
        new_updates: List of new RawPersonPropertyUpdates from the latest window query
    """
    for new_update in new_updates:
        person_id = new_update.person_id

        if person_id not in accumulated:
            accumulated[person_id] = RawPersonPropertyUpdates(
                person_id=person_id,
                set_updates=dict(new_update.set_updates),
                set_once_updates=dict(new_update.set_once_updates),
                unset_updates=dict(new_update.unset_updates),
            )
            continue

        existing = accumulated[person_id]

        # Process $set updates - newer timestamp wins
        for key, new_pv in new_update.set_updates.items():
            if key in existing.set_updates:
                if new_pv.timestamp > existing.set_updates[key].timestamp:
                    existing.set_updates[key] = new_pv
            else:
                existing.set_updates[key] = new_pv

        # Process $set_once updates - earlier timestamp wins
        for key, new_pv in new_update.set_once_updates.items():
            if key in existing.set_once_updates:
                if new_pv.timestamp < existing.set_once_updates[key].timestamp:
                    existing.set_once_updates[key] = new_pv
            else:
                existing.set_once_updates[key] = new_pv

        # Process $unset updates - newer timestamp wins
        for key, new_pv in new_update.unset_updates.items():
            if key in existing.unset_updates:
                if new_pv.timestamp > existing.unset_updates[key].timestamp:
                    existing.unset_updates[key] = new_pv
            else:
                existing.unset_updates[key] = new_pv


# Max number of person_ids per batch when querying person state.
# Prevents "Query size exceeded" errors when IN clause becomes too large.
# 10K UUIDs × ~40 chars ≈ 400KB query text, under typical max_query_size limits.
PERSON_STATE_BATCH_SIZE = 10000


def compare_raw_updates_with_person_state(
    team_id: int,
    raw_updates: list[RawPersonPropertyUpdates],
) -> list[PersonPropertyDiffs]:
    """
    Compare merged raw event updates against current person state in ClickHouse.

    This is the second step of the windowed query flow:
    1. get_raw_person_property_updates_from_clickhouse() per window
    2. merge_raw_person_property_updates() to combine windows
    3. compare_raw_updates_with_person_state() to filter to actual diffs

    Comparison rules (matching the original single-query behavior):
    - $set: only include if key EXISTS in person AND value DIFFERS
    - $set_once: only include if key does NOT exist in person
    - $unset: only include if key EXISTS in person

    Note on comparison semantics:
        This function uses Python object comparison, so semantically equal values
        like 123 (int) and 123.0 (float) are considered equal. This differs from
        the non-windowed SQL path (get_person_property_updates_from_clickhouse)
        which compares raw JSON string representations. The Python approach is
        preferable for reconciliation as it avoids unnecessary updates when
        values are semantically equivalent.

    Note on batching:
        For high-volume teams with many affected persons, we batch the person
        state queries to avoid "Query size exceeded" errors from overly large
        IN clauses. Each batch queries up to PERSON_STATE_BATCH_SIZE persons.

    Args:
        team_id: Team ID
        raw_updates: Merged raw updates from all time windows

    Returns:
        List of PersonPropertyDiffs with only actual differences
    """
    if not raw_updates:
        return []

    # Extract person_ids for batching
    person_ids = [u.person_id for u in raw_updates]

    # Query person properties and versions in batches to avoid "Query size exceeded"
    person_data: dict[str, tuple[dict, int]] = {}

    for batch_start in range(0, len(person_ids), PERSON_STATE_BATCH_SIZE):
        batch_person_ids = person_ids[batch_start : batch_start + PERSON_STATE_BATCH_SIZE]

        query = """
        SELECT
            id,
            argMax(properties, version) as properties,
            argMax(version, version) as person_version
        FROM person
        WHERE team_id = %(team_id)s
          AND id IN %(person_ids)s
        GROUP BY id
        HAVING argMax(is_deleted, version) = 0
        """

        params = {
            "team_id": team_id,
            "person_ids": tuple(batch_person_ids),
        }

        rows = sync_execute(query, params)

        for row in rows:
            person_id, properties_str, version = row
            if properties_str:
                properties = json.loads(properties_str) if isinstance(properties_str, str) else properties_str
            else:
                properties = {}
            person_data[str(person_id)] = (properties, int(version))

    results: list[PersonPropertyDiffs] = []

    for raw_update in raw_updates:
        if raw_update.person_id not in person_data:
            continue

        person_properties, person_version = person_data[raw_update.person_id]
        person_keys = set(person_properties.keys())

        # Filter $set: key must exist in person AND value must differ
        filtered_set: dict[str, PropertyValue] = {}
        for key, pv in raw_update.set_updates.items():
            if key in person_keys:
                person_val = person_properties[key]
                if pv.value != person_val:
                    filtered_set[key] = pv

        # Filter $set_once: key must NOT exist in person
        filtered_set_once: dict[str, PropertyValue] = {}
        for key, pv in raw_update.set_once_updates.items():
            if key not in person_keys:
                filtered_set_once[key] = pv

        # Filter $unset: key must exist in person
        filtered_unset: dict[str, PropertyValue] = {}
        for key, pv in raw_update.unset_updates.items():
            if key in person_keys:
                filtered_unset[key] = pv

        if filtered_set or filtered_set_once or filtered_unset:
            results.append(
                PersonPropertyDiffs(
                    person_id=raw_update.person_id,
                    person_version=person_version,
                    set_updates=filtered_set,
                    set_once_updates=filtered_set_once,
                    unset_updates=filtered_unset,
                )
            )

    return results


def parse_ch_timestamp(ts: str) -> datetime:
    """Parse a ClickHouse timestamp string to a UTC datetime."""
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def format_ch_timestamp(dt: datetime) -> str:
    """Format a datetime to ClickHouse timestamp string (UTC)."""
    if dt.tzinfo is None:
        # Assume naive datetimes are already UTC
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    # Convert to UTC before formatting
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%d %H:%M:%S")


def get_person_property_updates_windowed(
    team_id: int,
    bug_window_start: str,
    window_seconds: int,
    logger: Any = None,
) -> list[PersonPropertyDiffs]:
    """
    Fetch person property updates, optionally in time windows.

    When window_seconds > 0, this function uses a two-step flow:
    1. Query raw event aggregates per window (no person comparison)
    2. Merge raw updates across windows with timestamp-based deduplication
    3. Compare final merged updates against current person state

    When window_seconds <= 0, uses the original single-query approach.

    Args:
        team_id: Team ID to query
        bug_window_start: Start of time window (ClickHouse format: "YYYY-MM-DD HH:MM:SS")
        window_seconds: Size of each query window in seconds. If <= 0, single query is used.
        logger: Optional logger for progress tracking

    Returns:
        List of PersonPropertyDiffs with merged results across all windows
    """
    if window_seconds <= 0:
        if logger:
            logger.info(f"Using single-query mode for team_id={team_id}")
        return get_person_property_updates_from_clickhouse(team_id, bug_window_start)

    # Step 1 & 2: Query raw updates per window and merge
    accumulated: dict[str, RawPersonPropertyUpdates] = {}
    current_start = parse_ch_timestamp(bug_window_start)
    now = datetime.now(UTC)
    window_count = 0
    total_windows = int((now - current_start).total_seconds() / window_seconds) + 1

    if logger:
        logger.info(f"Starting windowed query: team_id={team_id}, ~{total_windows} windows of {window_seconds}s each")

    while current_start < now:
        current_end = min(current_start + timedelta(seconds=window_seconds), now)
        window_updates = get_raw_person_property_updates_from_clickhouse(
            team_id,
            format_ch_timestamp(current_start),
            format_ch_timestamp(current_end),
        )
        merge_raw_person_property_updates(accumulated, window_updates)
        window_count += 1

        if logger and window_count % 10 == 0:
            logger.info(
                f"Processed window {window_count}/{total_windows} for team_id={team_id}, "
                f"accumulated {len(accumulated)} unique persons"
            )

        current_start = current_end

    if logger:
        logger.info(
            f"Completed all {window_count} windows for team_id={team_id}, total unique persons: {len(accumulated)}"
        )

    # Step 3: Compare merged raw updates against person state
    if logger:
        logger.info(f"Comparing {len(accumulated)} persons against current state for team_id={team_id}")

    return compare_raw_updates_with_person_state(team_id, list(accumulated.values()))


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
                person_version=diffs.person_version,
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


def fetch_person_properties_from_clickhouse(team_id: int, person_uuid: str, min_version: int) -> dict | None:
    """
    Fetch person properties from ClickHouse for conflict resolution.

    Fetches the oldest available version >= min_version. This handles the case where
    the exact version we computed diffs against may have been merged away by
    ReplacingMergeTree background merges.

    Returns the properties at the oldest available version >= min_version, or None if not found.
    """
    query = """
    SELECT argMin(properties, version) as properties
    FROM person
    WHERE team_id = %(team_id)s AND id = %(person_id)s AND version >= %(min_version)s
    GROUP BY id
    """
    rows = sync_execute(query, {"team_id": team_id, "person_id": person_uuid, "min_version": min_version})
    if not rows:
        return None
    properties_str = rows[0][0]
    if not properties_str:
        return {}
    return json.loads(properties_str) if isinstance(properties_str, str) else properties_str


def reconcile_with_concurrent_changes(
    ch_properties: dict,
    postgres_person: dict,
    person_property_diffs: PersonPropertyDiffs,
) -> dict | None:
    """
    3-way merge: apply event changes while respecting concurrent Postgres changes.

    - Base: ch_properties (the state when event diffs were computed)
    - Theirs: postgres_person properties (current state, may have concurrent changes)
    - Ours: event_diffs (changes from events)

    Conflict resolution: Postgres wins (concurrent changes take precedence).
    This is conservative - we don't overwrite changes made by other processes.
    """
    postgres_properties = dict(postgres_person["properties"] or {})
    properties_last_updated_at = dict(postgres_person["properties_last_updated_at"] or {})
    properties_last_operation = dict(postgres_person["properties_last_operation"] or {})

    # Identify what changed in Postgres since CH (concurrent changes)
    concurrent_changed_keys: set[str] = set()
    all_keys = set(ch_properties.keys()) | set(postgres_properties.keys())
    for key in all_keys:
        ch_val = ch_properties.get(key)
        pg_val = postgres_properties.get(key)
        if ch_val != pg_val:
            concurrent_changed_keys.add(key)

    changed = False

    # 1. set_once: only update if key not in properties AND not concurrently changed
    for key, pv in person_property_diffs.set_once_updates.items():
        if key not in postgres_properties and key not in concurrent_changed_keys:
            postgres_properties[key] = pv.value
            properties_last_updated_at[key] = pv.timestamp.isoformat()
            properties_last_operation[key] = "set_once"
            changed = True

    # 2. set: only update if not concurrently changed
    for key, pv in person_property_diffs.set_updates.items():
        if key not in concurrent_changed_keys:
            postgres_properties[key] = pv.value
            properties_last_updated_at[key] = pv.timestamp.isoformat()
            properties_last_operation[key] = "set"
            changed = True

    # 3. unset: only delete if not concurrently changed
    for key in person_property_diffs.unset_updates.keys():
        if key in postgres_properties and key not in concurrent_changed_keys:
            del postgres_properties[key]
            if key in properties_last_updated_at:
                del properties_last_updated_at[key]
            if key in properties_last_operation:
                del properties_last_operation[key]
            changed = True

    if changed:
        return {
            "properties": postgres_properties,
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
    return cursor.rowcount > 0


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
    Update a person's properties with optimistic locking and conflict resolution.

    Flow:
    1. Fetch person from Postgres
    2. If Postgres version == CH version: apply diffs normally, UPDATE WHERE version = ch_version
    3. If versions differ (conflict): fetch CH properties, do 3-way merge, UPDATE WHERE version = postgres_version
    4. On UPDATE failure, retry

    Args:
        cursor: Database cursor
        job_id: Dagster run ID for backup tracking
        team_id: Team ID
        person_uuid: Person UUID
        person_property_diffs: Property diffs from ClickHouse (includes person_version)
        dry_run: If True, don't actually write the UPDATE
        backup_enabled: If True, store before/after state in backup table
        max_retries: Maximum retry attempts on version mismatch

    Returns:
        Tuple of (success: bool, updated_person_data: dict | None, backup_created: bool, skip_reason: str)
        updated_person_data contains the final state for Kafka publishing
        backup_created indicates if a backup row was inserted
        skip_reason indicates why the person was skipped (see SkipReason class)
    """
    ch_version = person_property_diffs.person_version

    for _attempt in range(max_retries):
        # Fetch current person state from Postgres
        person = fetch_person_from_postgres(cursor, team_id, person_uuid)
        if not person:
            return False, None, False, SkipReason.NOT_FOUND

        postgres_version = person.get("version") or 0

        # Check if Postgres and CH are in sync
        if postgres_version == ch_version:
            # Simple case: no concurrent changes, apply diffs directly
            update = reconcile_person_properties(person, person_property_diffs)
            target_version = ch_version
        else:
            # Conflict: Postgres has different version than CH
            # Fetch CH properties at the version we computed diffs against for 3-way merge
            ch_properties = fetch_person_properties_from_clickhouse(team_id, person_uuid, ch_version)
            if ch_properties is None:
                # Person version doesn't exist in CH anymore, skip
                return False, None, False, SkipReason.NOT_FOUND

            # 3-way merge: apply our changes while respecting concurrent Postgres changes
            update = reconcile_with_concurrent_changes(ch_properties, person, person_property_diffs)
            target_version = postgres_version

        if not update:
            # No changes needed (either no diffs or all conflicts resolved to Postgres values)
            return True, None, False, SkipReason.NO_CHANGES

        # Backup before and after state for audit/rollback
        backup_created = False
        if backup_enabled:
            backup_created = backup_person_with_computed_state(
                cursor, job_id, team_id, person, person_property_diffs, update, target_version + 1
            )

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
                target_version + 1,
                team_id,
                person_uuid,
                target_version,
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
                    "version": target_version + 1,
                },
                backup_created,
                SkipReason.SUCCESS,
            )

        # Version mismatch during UPDATE - retry with fresh data
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


def query_team_ids_from_clickhouse(
    bug_window_start: str,
    bug_window_end: str,
    min_team_id: int | None = None,
    max_team_id: int | None = None,
    exclude_team_ids: list[int] | None = None,
    include_team_ids: list[int] | None = None,
) -> list[int]:
    """
    Query ClickHouse for distinct team_ids with property-setting events in the bug window.

    Args:
        bug_window_start: Start of bug window (CH format: "YYYY-MM-DD HH:MM:SS")
        bug_window_end: End of bug window (CH format: "YYYY-MM-DD HH:MM:SS")
        min_team_id: Optional minimum team_id (inclusive)
        max_team_id: Optional maximum team_id (inclusive)
        exclude_team_ids: Optional list of team_ids to exclude
        include_team_ids: Optional list of team_ids to include (only these teams will be queried)

    Returns:
        List of team_ids sorted ascending

    Raises:
        ValueError: If min_team_id > max_team_id
    """
    if min_team_id is not None and max_team_id is not None and min_team_id > max_team_id:
        raise ValueError(
            f"Invalid team_id range: min_team_id ({min_team_id}) cannot be greater than max_team_id ({max_team_id})"
        )

    team_id_filters = []
    params: dict[str, Any] = {
        "bug_window_start": bug_window_start,
        "bug_window_end": bug_window_end,
    }

    if include_team_ids:
        team_id_filters.append("team_id IN %(include_team_ids)s")
        params["include_team_ids"] = tuple(include_team_ids)

    if min_team_id is not None:
        team_id_filters.append("team_id >= %(min_team_id)s")
        params["min_team_id"] = min_team_id

    if max_team_id is not None:
        team_id_filters.append("team_id <= %(max_team_id)s")
        params["max_team_id"] = max_team_id

    if exclude_team_ids:
        team_id_filters.append("team_id NOT IN %(exclude_team_ids)s")
        params["exclude_team_ids"] = tuple(exclude_team_ids)

    team_id_filter_clause = (" AND " + " AND ".join(team_id_filters)) if team_id_filters else ""

    query = f"""
        SELECT DISTINCT team_id
        FROM events
        WHERE timestamp >= %(bug_window_start)s
          AND timestamp < %(bug_window_end)s
          AND (
            JSONHas(properties, '$set') = 1
            OR JSONHas(properties, '$set_once') = 1
            OR JSONHas(properties, '$unset') = 1
          ){team_id_filter_clause}
        ORDER BY team_id
    """

    results = sync_execute(query, params)
    return [int(row[0]) for row in results]


@dagster.op
def get_team_ids_to_reconcile(
    context: dagster.OpExecutionContext,
    config: PersonPropertyReconciliationConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    """
    Query ClickHouse for distinct team_ids with property-setting events in the bug window.
    """
    if not config.bug_window_end:
        raise dagster.Failure(
            description="bug_window_end must be provided",
            metadata={
                "bug_window_start": dagster.MetadataValue.text(config.bug_window_start),
            },
        )

    filter_info_parts = []
    if config.team_ids:
        filter_info_parts.append(f"team_ids: {config.team_ids}")
    if config.min_team_id is not None or config.max_team_id is not None:
        filter_info_parts.append(f"range: {config.min_team_id or 'any'} to {config.max_team_id or 'any'}")
    if config.exclude_team_ids:
        filter_info_parts.append(f"excluding: {config.exclude_team_ids}")
    filter_info = f" ({', '.join(filter_info_parts)})" if filter_info_parts else ""

    context.log.info(
        f"Querying for team_ids with property events between {config.bug_window_start} and {config.bug_window_end}{filter_info}"
    )

    team_ids = query_team_ids_from_clickhouse(
        bug_window_start=config.bug_window_start,
        bug_window_end=config.bug_window_end,
        min_team_id=config.min_team_id,
        max_team_id=config.max_team_id,
        exclude_team_ids=config.exclude_team_ids,
        include_team_ids=config.team_ids,
    )

    if not team_ids:
        context.log.info("No team IDs found with property events in bug window")
        return []

    context.log.info(f"Found {len(team_ids)} teams with property events")
    context.log.info(f"Sample of teams to process: {team_ids[:10]}" + ("..." if len(team_ids) > 10 else ""))
    context.add_output_metadata({"team_count": dagster.MetadataValue.int(len(team_ids))})

    return team_ids


@dagster.op(out=dagster.DynamicOut(list[int]))
def create_team_chunks(
    context: dagster.OpExecutionContext,
    config: PersonPropertyReconciliationConfig,
    team_ids: list[int],
):
    """
    Create chunks of team_ids based on teams_per_chunk config.
    Yields DynamicOutput for each chunk containing one or more teams.
    """
    if not team_ids:
        context.log.info("No teams to process")
        return

    teams_per_chunk = max(1, config.teams_per_chunk)
    num_chunks = (len(team_ids) + teams_per_chunk - 1) // teams_per_chunk
    context.log.info(f"Creating {num_chunks} chunks for {len(team_ids)} teams (teams_per_chunk={teams_per_chunk})")

    for i in range(0, len(team_ids), teams_per_chunk):
        chunk = team_ids[i : i + teams_per_chunk]
        chunk_key = f"teams_{chunk[0]}_{chunk[-1]}" if len(chunk) > 1 else f"team_{chunk[0]}"
        context.log.info(
            f"Yielding chunk with {len(chunk)} teams: {chunk[0]}-{chunk[-1] if len(chunk) > 1 else chunk[0]}"
        )
        yield dagster.DynamicOutput(
            value=chunk,
            mapping_key=chunk_key,
        )


@dataclass
class TeamReconciliationResult:
    """Result of reconciling a single team."""

    team_id: int
    persons_processed: int
    persons_updated: int
    persons_skipped: int


def reconcile_single_team(
    team_id: int,
    bug_window_start: str,
    run_id: str,
    batch_size: int,
    dry_run: bool,
    backup_enabled: bool,
    team_ch_props_fetch_window_seconds: int,
    persons_database: psycopg2.extensions.connection,
    kafka_producer: _KafkaProducer,
    logger: Any,
) -> TeamReconciliationResult:
    """
    Reconcile person properties for all affected persons in a single team.

    This function does not catch exceptions - the caller is responsible for error handling.
    """
    # Query ClickHouse for all persons with property updates in this team
    logger.info(
        f"Querying ClickHouse for property updates: team_id={team_id}, "
        f"bug_window_start={bug_window_start}, window_seconds={team_ch_props_fetch_window_seconds}"
    )
    person_property_diffs = get_person_property_updates_windowed(
        team_id=team_id,
        bug_window_start=bug_window_start,
        window_seconds=team_ch_props_fetch_window_seconds,
        logger=logger,
    )
    logger.info(f"Found {len(person_property_diffs)} persons with property diffs for team_id={team_id}")

    # Filter conflicting set/unset operations
    person_property_diffs = filter_event_person_properties(person_property_diffs)

    if not person_property_diffs:
        logger.info(f"No persons to reconcile for team_id={team_id}")
        return TeamReconciliationResult(
            team_id=team_id,
            persons_processed=0,
            persons_updated=0,
            persons_skipped=0,
        )

    logger.info(f"Processing {len(person_property_diffs)} persons for team_id={team_id}")

    # Callback for batch commits - handles Kafka publishing after each batch
    def on_batch_committed(batch_num: int, batch_persons: list[dict]) -> None:
        if batch_persons and not dry_run:
            for person_data in batch_persons:
                try:
                    publish_person_to_kafka(person_data, kafka_producer)
                except Exception as kafka_error:
                    logger.warning(f"Failed to publish person to Kafka: {person_data['id']}, error: {kafka_error}")
            try:
                kafka_producer.flush()
            except Exception as flush_error:
                logger.warning(f"Failed to flush Kafka producer: {flush_error}")

            logger.info(f"Batch {batch_num}: committed {len(batch_persons)} updates for team_id={team_id}")
        elif batch_persons and dry_run:
            logger.info(f"[DRY RUN] Batch {batch_num}: would apply {len(batch_persons)} updates for team_id={team_id}")

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
            batch_size=batch_size,
            dry_run=dry_run,
            backup_enabled=backup_enabled,
            commit_fn=persons_database.commit,
            on_batch_committed=on_batch_committed,
            logger=logger,
        )

    logger.info(
        f"Completed team_id={team_id}: processed={result.total_processed}, "
        f"updated={result.total_updated}, skipped={result.total_skipped}"
    )

    return TeamReconciliationResult(
        team_id=team_id,
        persons_processed=result.total_processed,
        persons_updated=result.total_updated,
        persons_skipped=result.total_skipped,
    )


@dagster.op
def reconcile_team_chunk(
    context: dagster.OpExecutionContext,
    config: PersonPropertyReconciliationConfig,
    chunk: list[int],
    persons_database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
    kafka_producer: dagster.ResourceParam[_KafkaProducer],
) -> dict[str, Any]:
    """
    Reconcile person properties for all affected persons in a chunk of teams.
    """
    team_ids = chunk
    chunk_id = f"teams_{team_ids[0]}_{team_ids[-1]}" if len(team_ids) > 1 else f"team_{team_ids[0]}"
    job_name = context.run.job_name
    run_id = context.run.run_id

    metrics_client = MetricsClient(cluster)

    context.log.info(
        f"Starting reconciliation for {len(team_ids)} teams: {team_ids}, "
        f"bug_window_start: {config.bug_window_start}, "
        f"dry_run: {config.dry_run}"
    )

    total_persons_processed = 0
    total_persons_updated = 0
    total_persons_skipped = 0
    total_teams_succeeded = 0
    total_teams_failed = 0
    teams_results: list[dict[str, Any]] = []

    start_time = time.time()

    for team_id in team_ids:
        team_result: dict[str, Any] = {
            "team_id": team_id,
            "status": "success",
            "persons_processed": 0,
            "persons_updated": 0,
            "persons_skipped": 0,
        }

        try:
            result = reconcile_single_team(
                team_id=team_id,
                bug_window_start=config.bug_window_start,
                run_id=run_id,
                batch_size=config.batch_size,
                dry_run=config.dry_run,
                backup_enabled=config.backup_enabled,
                team_ch_props_fetch_window_seconds=config.team_ch_props_fetch_window_seconds,
                persons_database=persons_database,
                kafka_producer=kafka_producer,
                logger=context.log,
            )
            team_result["persons_processed"] = result.persons_processed
            team_result["persons_updated"] = result.persons_updated
            team_result["persons_skipped"] = result.persons_skipped
            total_teams_succeeded += 1

        except Exception as e:
            team_result["status"] = "failed"
            team_result["error"] = str(e)
            total_teams_failed += 1

            context.log.exception(f"Failed team_id={team_id}: {e}")

            try:
                metrics_client.increment(
                    "person_property_reconciliation_error",
                    labels={"job_name": job_name, "chunk_id": chunk_id, "team_id": str(team_id), "reason": "error"},
                    value=1.0,
                ).result()
            except Exception:
                pass

        total_persons_processed += team_result["persons_processed"]
        total_persons_updated += team_result["persons_updated"]
        total_persons_skipped += team_result["persons_skipped"]
        teams_results.append(team_result)

    # Track metrics for the entire chunk
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
        metrics_client.increment(
            "person_property_reconciliation_teams_succeeded_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_teams_succeeded),
        ).result()
        metrics_client.increment(
            "person_property_reconciliation_teams_failed_total",
            labels={"job_name": job_name, "chunk_id": chunk_id},
            value=float(total_teams_failed),
        ).result()
    except Exception:
        pass

    # Log failed teams for easy searching
    failed_teams = [r for r in teams_results if r["status"] == "failed"]
    if failed_teams:
        failed_team_ids = [r["team_id"] for r in failed_teams]
        context.log.warning(f"Failed teams in chunk {chunk_id}: {failed_team_ids}")

    context.log.info(
        f"Completed chunk {chunk_id}: teams={len(team_ids)} (succeeded={total_teams_succeeded}, failed={total_teams_failed}), "
        f"persons: processed={total_persons_processed}, updated={total_persons_updated}, skipped={total_persons_skipped}"
    )

    context.add_output_metadata(
        {
            "team_ids": dagster.MetadataValue.text(str(team_ids)),
            "teams_count": dagster.MetadataValue.int(len(team_ids)),
            "teams_succeeded": dagster.MetadataValue.int(total_teams_succeeded),
            "teams_failed": dagster.MetadataValue.int(total_teams_failed),
            "failed_team_ids": dagster.MetadataValue.text(str([r["team_id"] for r in failed_teams])),
            "persons_processed": dagster.MetadataValue.int(total_persons_processed),
            "persons_updated": dagster.MetadataValue.int(total_persons_updated),
            "persons_skipped": dagster.MetadataValue.int(total_persons_skipped),
            "teams_results": dagster.MetadataValue.json(teams_results),
        }
    )

    return {
        "team_ids": team_ids,
        "teams_count": len(team_ids),
        "teams_succeeded": total_teams_succeeded,
        "teams_failed": total_teams_failed,
        "persons_processed": total_persons_processed,
        "persons_updated": total_persons_updated,
        "persons_skipped": total_persons_skipped,
        "teams_results": teams_results,
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


# --- Sensor-based scheduler for automated batch reconciliation ---


class ReconciliationSchedulerConfig(dagster.Config):
    """Configuration for the reconciliation scheduler sensor.

    This sensor automates launching multiple reconciliation jobs across a range
    of team IDs while respecting concurrency limits.

    You must provide EITHER:
    - team_ids: explicit list of team IDs to process
    - OR both range_start and range_end: to scan a team ID range
    """

    # Option 1: Explicit list of team IDs
    team_ids: list[int] | None = None

    # Option 2: Range-based scanning
    range_start: int | None = None  # First team_id (inclusive)
    range_end: int | None = None  # Last team_id (inclusive)

    chunk_size: int = 1000  # Teams per job run (for range mode) or list chunk size (for team_ids mode)
    max_concurrent_jobs: int = 5  # Max reconciliation jobs the sensor can schedule at once
    max_concurrent_tasks: int = 10  # Max k8s pods per job (executor concurrency)

    # Base job configuration (applied to all runs)
    bug_window_start: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS"
    bug_window_end: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS"
    dry_run: bool = False
    backup_enabled: bool = True
    batch_size: int = 100
    teams_per_chunk: int = 100  # Number of teams to process per task
    team_ch_props_fetch_window_seconds: int = 0  # 0 = single query; >0 = split into N-second windows

    # Resource configuration - the env var name for the PG connection string
    persons_db_env_var: str = "PERSONS_DB_WRITER_URL"  # Env var for Postgres connection URL


def build_reconciliation_run_config(
    config: ReconciliationSchedulerConfig,
    min_team_id: int | None = None,
    max_team_id: int | None = None,
    team_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Build run config for a single reconciliation job.

    Either provide team_ids (explicit list) OR min_team_id/max_team_id (range scan).
    """
    op_config: dict[str, Any] = {
        "bug_window_start": config.bug_window_start,
        "bug_window_end": config.bug_window_end,
        "dry_run": config.dry_run,
        "backup_enabled": config.backup_enabled,
        "batch_size": config.batch_size,
        "teams_per_chunk": config.teams_per_chunk,
        "team_ch_props_fetch_window_seconds": config.team_ch_props_fetch_window_seconds,
    }

    if team_ids is not None:
        op_config["team_ids"] = team_ids
    else:
        op_config["min_team_id"] = min_team_id
        op_config["max_team_id"] = max_team_id

    return {
        "execution": {"config": {"max_concurrent": config.max_concurrent_tasks}},
        "ops": {
            "get_team_ids_to_reconcile": {"config": op_config},
            "create_team_chunks": {"config": op_config},
            "reconcile_team_chunk": {"config": op_config},
        },
        "resources": {
            "cluster": {
                "config": {
                    "client_settings": {
                        "lightweight_deletes_sync": "0",
                        "max_execution_time": "0",
                        "max_memory_usage": "0",
                        "mutations_sync": "0",
                        "receive_timeout": "900",
                    }
                }
            },
            "persons_database": {"config": {"connection_url": {"env": config.persons_db_env_var}}},
        },
    }


@dagster.sensor(
    job=person_property_reconciliation_job,
    minimum_interval_seconds=30,
    default_status=dagster.DefaultSensorStatus.STOPPED,
)
def person_property_reconciliation_scheduler(context: dagster.SensorEvaluationContext):
    """
    Sensor that automatically schedules person property reconciliation jobs.

    Supports two modes:
    1. team_ids mode: Process an explicit list of team IDs
    2. range mode: Scan a team_id range (range_start to range_end)

    Splits work into chunks and launches jobs up to max_concurrent_jobs,
    tracking progress via cursor. Enable via Dagster UI after configuring.

    Cursor format (team_ids mode):
        {"team_ids": [1, 2, 3, ...], "next_team_index": 0, ...}
    Cursor format (range mode):
        {"range_start": 1, "range_end": 10000, "next_chunk_start": 1, ...}

    Configuration (set via Dagster UI or launchpad):
    - team_ids: Explicit list of team IDs (mutually exclusive with range_start/range_end)
    - range_start/range_end: Team ID range to process (inclusive)
    - chunk_size: Number of teams per job (default 1000)
    - max_concurrent_jobs: Max reconciliation jobs sensor can schedule at once (default 5, cap 50)
    - max_concurrent_tasks: Max k8s pods per job / executor concurrency (default 10, cap 100)
    - bug_window_start/end: Time window for the reconciliation
    - dry_run, backup_enabled, batch_size: Passed to each job
    """
    sensor_config_raw = context.cursor

    if not sensor_config_raw:
        return dagster.SkipReason(
            "No cursor set. Initialize by setting cursor to JSON. "
            'For team_ids mode: {"team_ids": [1, 2, 3], "chunk_size": 100, ...}. '
            'For range mode: {"range_start": 1, "range_end": 10000, "chunk_size": 1000, ...}. '
            'Common fields: "max_concurrent_jobs", "max_concurrent_tasks", "bug_window_start", "bug_window_end", '
            '"dry_run", "backup_enabled", "batch_size"'
        )

    try:
        cursor_data = json.loads(sensor_config_raw)
    except json.JSONDecodeError:
        return dagster.SkipReason(f"Invalid cursor JSON: {sensor_config_raw[:100]}...")

    # Extract common config
    chunk_size = cursor_data.get("chunk_size", 1000)
    max_concurrent_jobs = cursor_data.get("max_concurrent_jobs", 5)
    max_concurrent_tasks = cursor_data.get("max_concurrent_tasks", 10)
    bug_window_start = cursor_data.get("bug_window_start", "")
    bug_window_end = cursor_data.get("bug_window_end", "")

    # Determine mode: team_ids vs range
    team_ids = cursor_data.get("team_ids")
    range_start = cursor_data.get("range_start")
    range_end = cursor_data.get("range_end")

    has_team_ids = team_ids is not None and len(team_ids) > 0
    has_range = range_start is not None and range_end is not None

    # Validate: must have exactly one mode
    if has_team_ids and has_range:
        return dagster.SkipReason(
            "Invalid config: cannot specify both team_ids and range_start/range_end. Choose one mode."
        )
    if not has_team_ids and not has_range:
        return dagster.SkipReason(
            "Invalid config: must specify either team_ids (list) OR both range_start and range_end"
        )

    # Validate common config
    MAX_CONCURRENT_JOBS_CAP = 50
    MAX_CONCURRENT_TASKS_CAP = 100
    if chunk_size <= 0:
        return dagster.SkipReason(f"Invalid config: chunk_size must be > 0, got {chunk_size}")
    if max_concurrent_jobs <= 0:
        return dagster.SkipReason(f"Invalid config: max_concurrent_jobs must be > 0, got {max_concurrent_jobs}")
    if max_concurrent_jobs > MAX_CONCURRENT_JOBS_CAP:
        return dagster.SkipReason(
            f"Invalid config: max_concurrent_jobs ({max_concurrent_jobs}) exceeds cap of {MAX_CONCURRENT_JOBS_CAP}"
        )
    if max_concurrent_tasks <= 0:
        return dagster.SkipReason(f"Invalid config: max_concurrent_tasks must be > 0, got {max_concurrent_tasks}")
    if max_concurrent_tasks > MAX_CONCURRENT_TASKS_CAP:
        return dagster.SkipReason(
            f"Invalid config: max_concurrent_tasks ({max_concurrent_tasks}) exceeds cap of {MAX_CONCURRENT_TASKS_CAP}"
        )
    if not bug_window_start:
        return dagster.SkipReason("Invalid config: bug_window_start is required")
    if not bug_window_end:
        return dagster.SkipReason("Invalid config: bug_window_end is required")

    # Mode-specific validation
    if has_range and range_start > range_end:
        return dagster.SkipReason(
            f"Invalid config: range_start ({range_start}) cannot be greater than range_end ({range_end})"
        )

    # Build config object for run config generation
    config = ReconciliationSchedulerConfig(
        team_ids=team_ids if has_team_ids else None,
        range_start=range_start if has_range else None,
        range_end=range_end if has_range else None,
        chunk_size=chunk_size,
        max_concurrent_jobs=max_concurrent_jobs,
        max_concurrent_tasks=max_concurrent_tasks,
        bug_window_start=bug_window_start,
        bug_window_end=bug_window_end,
        dry_run=cursor_data.get("dry_run", False),
        backup_enabled=cursor_data.get("backup_enabled", True),
        batch_size=cursor_data.get("batch_size", 100),
        teams_per_chunk=cursor_data.get("teams_per_chunk", 100),
        team_ch_props_fetch_window_seconds=cursor_data.get("team_ch_props_fetch_window_seconds", 0),
        persons_db_env_var=cursor_data.get("persons_db_env_var", "PERSONS_DB_WRITER_URL"),
    )

    # Count active runs for this job
    active_runs = context.instance.get_run_records(
        dagster.RunsFilter(
            job_name="person_property_reconciliation_job",
            statuses=[
                dagster.DagsterRunStatus.QUEUED,
                dagster.DagsterRunStatus.NOT_STARTED,
                dagster.DagsterRunStatus.STARTING,
                dagster.DagsterRunStatus.STARTED,
            ],
        )
    )
    active_count = len(active_runs)

    available_slots = max(0, max_concurrent_jobs - active_count)
    if available_slots == 0:
        return dagster.SkipReason(f"At max concurrency ({active_count}/{max_concurrent_jobs} jobs), waiting for slots")

    context.log.info(f"Active runs: {active_count}/{max_concurrent_jobs}, available slots: {available_slots}")

    # Generate run requests based on mode
    run_requests: list[dagster.RunRequest] = []

    if has_team_ids:
        # Team IDs mode: chunk the list
        next_team_index = cursor_data.get("next_team_index", 0)

        if next_team_index >= len(team_ids):
            return dagster.SkipReason(f"Reconciliation complete: processed all {len(team_ids)} teams")

        while len(run_requests) < available_slots and next_team_index < len(team_ids):
            chunk_end_index = min(next_team_index + chunk_size, len(team_ids))
            chunk_team_ids = team_ids[next_team_index:chunk_end_index]

            run_config = build_reconciliation_run_config(
                config=config,
                team_ids=chunk_team_ids,
            )

            context.log.info(
                f"Scheduling run for team_ids[{next_team_index}:{chunk_end_index}] ({len(chunk_team_ids)} teams)"
            )

            run_requests.append(
                dagster.RunRequest(
                    run_config=run_config,
                    tags={
                        "reconciliation_team_ids_range": f"{next_team_index}-{chunk_end_index - 1}",
                        "reconciliation_team_count": str(len(chunk_team_ids)),
                        "owner": JobOwners.TEAM_INGESTION.value,
                    },
                )
            )

            next_team_index = chunk_end_index

        # Update cursor
        cursor_data["next_team_index"] = next_team_index
        new_cursor = json.dumps(cursor_data)
        context.log.info(f"Scheduled {len(run_requests)} runs, next_team_index: {next_team_index}")

    else:
        # Range mode: existing behavior
        next_chunk_start = cursor_data.get("next_chunk_start", range_start)

        if next_chunk_start > range_end:
            return dagster.SkipReason(f"Reconciliation complete: processed all teams up to {range_end}")

        current_start = next_chunk_start

        while len(run_requests) < available_slots and current_start <= range_end:
            chunk_end = min(current_start + chunk_size - 1, range_end)

            run_config = build_reconciliation_run_config(
                config=config,
                min_team_id=current_start,
                max_team_id=chunk_end,
            )

            context.log.info(f"Scheduling run for teams {current_start}-{chunk_end}")

            run_requests.append(
                dagster.RunRequest(
                    run_config=run_config,
                    tags={
                        "reconciliation_range": f"{current_start}-{chunk_end}",
                        "owner": JobOwners.TEAM_INGESTION.value,
                    },
                )
            )

            current_start = chunk_end + 1

        # Update cursor
        cursor_data["next_chunk_start"] = current_start
        new_cursor = json.dumps(cursor_data)
        context.log.info(f"Scheduled {len(run_requests)} runs, next_chunk_start: {current_start}")

    return dagster.SensorResult(run_requests=run_requests, cursor=new_cursor)
