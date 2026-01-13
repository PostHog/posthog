"""Dagster job for reconciling event person_properties that were missed due to a bug.

Each event has a person_properties field that should reflect the accumulated state
of a person's properties at the time that event occurred. This job recalculates
those values based on $set/$set_once operations in the bug window.

Strategy (optimized for minimal events table scans):
1. Single scan of events → tmp_events_window (all data we need)
2. Compute checkpoints from tmp_events_window (self-join on small dataset)
3. ASOF JOIN to assign states (fast O(n log n))
4. Update events

This reduces events table scans from 6+ to 1.
"""

from django.conf import settings

import dagster
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners

executor_def = dagster.in_process_executor if settings.DEBUG else k8s_job_executor


class EventPersonPropertiesReconciliationConfig(dagster.Config):
    """Configuration for the event person properties reconciliation job."""

    bug_window_start: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS" (UTC)
    bug_window_end: str  # ClickHouse format: "YYYY-MM-DD HH:MM:SS" (UTC)
    team_ids: list[int] | None = None


# ============================================================================
# Temp table DDL
# ============================================================================


def create_events_window_table_sql() -> str:
    """Temp table for single events scan - contains all data needed for reconciliation."""
    return """
        CREATE TABLE IF NOT EXISTS tmp_events_window (
            team_id UInt64,
            uuid UUID,
            person_id UUID,
            timestamp DateTime64(6, 'UTC'),
            set_map Map(String, String),
            set_once_map Map(String, String)
        )
        ENGINE = MergeTree()
        ORDER BY (team_id, person_id, timestamp)
    """


def create_checkpoints_table_sql() -> str:
    """Temp table for accumulated state at each $set event."""
    return """
        CREATE TABLE IF NOT EXISTS tmp_set_checkpoints (
            team_id UInt64,
            person_id UUID,
            checkpoint_ts DateTime64(6, 'UTC'),
            accumulated_props String
        )
        ENGINE = MergeTree()
        ORDER BY (team_id, person_id, checkpoint_ts)
    """


def create_results_table_sql() -> str:
    """Temp table for final calculated person_properties."""
    return """
        CREATE TABLE IF NOT EXISTS tmp_event_person_props_reconciliation (
            team_id UInt64,
            uuid UUID,
            calculated_person_properties String
        )
        ENGINE = MergeTree()
        ORDER BY (team_id, uuid)
    """


def drop_events_window_table_sql() -> str:
    return "DROP TABLE IF EXISTS tmp_events_window"


def drop_checkpoints_table_sql() -> str:
    return "DROP TABLE IF EXISTS tmp_set_checkpoints"


def drop_results_table_sql() -> str:
    return "DROP TABLE IF EXISTS tmp_event_person_props_reconciliation"


# ============================================================================
# Step 1: Single events scan into temp table
# ============================================================================


def populate_events_window_sql(team_id: int, bug_window_start: str, bug_window_end: str) -> str:
    """
    Single scan of events table - extracts all data needed for reconciliation.
    
    This is THE ONLY query that reads from the events table.
    All subsequent queries read from tmp_events_window.
    """
    return f"""
        INSERT INTO tmp_events_window
        WITH
            overrides AS (
                SELECT argMax(person_id, version) AS person_id, distinct_id
                FROM person_distinct_id_overrides
                WHERE team_id = {team_id}
                GROUP BY distinct_id
                HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
            )
        SELECT 
            {team_id} as team_id,
            e.uuid,
            if(notEmpty(o.distinct_id), o.person_id, e.person_id) as person_id,
            e.timestamp,
            CAST(
                if(JSONHas(e.properties, '$set'),
                   JSONExtractKeysAndValues(e.properties, '$set', 'String'),
                   []),
                'Map(String, String)'
            ) as set_map,
            CAST(
                if(JSONHas(e.properties, '$set_once'),
                   JSONExtractKeysAndValues(e.properties, '$set_once', 'String'),
                   []),
                'Map(String, String)'
            ) as set_once_map
        FROM events e
        LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
        WHERE e.team_id = {team_id}
          AND e.timestamp >= '{bug_window_start}'
          AND e.timestamp <= '{bug_window_end}'

        SETTINGS 
            max_execution_time = 3600,
            allow_experimental_analyzer = 1
    """


# ============================================================================
# Step 2: Compute checkpoints from tmp_events_window
# ============================================================================


def populate_checkpoints_sql(team_id: int, bug_window_start: str) -> str:
    """
    Compute accumulated state at each $set event.
    
    Reads from tmp_events_window (not events table).
    Self-join only on events with $set (much smaller dataset).
    """
    return f"""
        INSERT INTO tmp_set_checkpoints
        WITH
            -- Base person properties BEFORE the bug window
            base_props AS (
                SELECT 
                    id as person_id,
                    CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
                FROM person
                WHERE team_id = {team_id}
                  AND id IN (SELECT DISTINCT person_id FROM tmp_events_window WHERE team_id = {team_id})
                  AND _timestamp < '{bug_window_start}'
                GROUP BY id
            ),
            
            -- Only events with $set (filter from temp table)
            set_events AS (
                SELECT person_id, uuid, timestamp, set_map
                FROM tmp_events_window
                WHERE team_id = {team_id}
                  AND length(mapKeys(set_map)) > 0
            ),
            
            -- Self-join to accumulate $set values
            set_key_values AS (
                SELECT 
                    target.uuid,
                    target.person_id,
                    target.timestamp,
                    source_kv.1 as key,
                    argMax(source_kv.2, source.timestamp) as value
                FROM set_events target
                INNER JOIN set_events source 
                    ON target.person_id = source.person_id
                    AND source.timestamp <= target.timestamp
                ARRAY JOIN source.set_map as source_kv
                GROUP BY target.uuid, target.person_id, target.timestamp, source_kv.1
            ),
            
            accumulated_set AS (
                SELECT 
                    uuid,
                    person_id,
                    timestamp,
                    CAST(groupArray((key, value)), 'Map(String, String)') as set_map
                FROM set_key_values
                GROUP BY uuid, person_id, timestamp
            ),
            
            -- $set_once: first value per key per person (from temp table)
            set_once_per_person AS (
                SELECT 
                    person_id,
                    CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
                FROM (
                    SELECT 
                        person_id,
                        kv.1 as key, 
                        argMin(kv.2, timestamp) as first_value
                    FROM tmp_events_window
                    ARRAY JOIN set_once_map as kv
                    WHERE team_id = {team_id}
                      AND length(mapKeys(set_once_map)) > 0
                    GROUP BY person_id, kv.1
                )
                GROUP BY person_id
            )

        SELECT 
            {team_id} as team_id,
            a.person_id,
            a.timestamp as checkpoint_ts,
            toJSONString(
                mapUpdate(
                    mapUpdate(
                        COALESCE(b.props_map, map()),
                        mapFilter((k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k), COALESCE(so.set_once_map, map()))
                    ),
                    a.set_map
                )
            ) as accumulated_props
        FROM accumulated_set a
        LEFT JOIN base_props b ON a.person_id = b.person_id
        LEFT JOIN set_once_per_person so ON a.person_id = so.person_id

        SETTINGS 
            max_execution_time = 3600, 
            max_bytes_before_external_group_by = 10000000000, 
            allow_experimental_analyzer = 1
    """


# ============================================================================
# Step 3: ASOF JOIN to assign states to all events
# ============================================================================


def populate_results_sql(team_id: int, bug_window_start: str) -> str:
    """
    Use ASOF JOIN to assign accumulated state to ALL events.
    
    Reads from tmp_events_window and tmp_set_checkpoints (not events table).
    """
    return f"""
        INSERT INTO tmp_event_person_props_reconciliation
        WITH
            base_props AS (
                SELECT 
                    id as person_id,
                    CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
                FROM person
                WHERE team_id = {team_id}
                  AND id IN (SELECT DISTINCT person_id FROM tmp_events_window WHERE team_id = {team_id})
                  AND _timestamp < '{bug_window_start}'
                GROUP BY id
            ),
            
            -- $set_once per person (from temp table)
            set_once_per_person AS (
                SELECT 
                    person_id,
                    CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
                FROM (
                    SELECT 
                        person_id,
                        kv.1 as key, 
                        argMin(kv.2, timestamp) as first_value
                    FROM tmp_events_window
                    ARRAY JOIN set_once_map as kv
                    WHERE team_id = {team_id}
                      AND length(mapKeys(set_once_map)) > 0
                    GROUP BY person_id, kv.1
                )
                GROUP BY person_id
            )

        SELECT 
            {team_id} as team_id,
            t.uuid,
            if(
                c.accumulated_props IS NOT NULL AND c.accumulated_props != '',
                c.accumulated_props,
                -- No checkpoint = no $set events before this, use base + set_once
                toJSONString(
                    mapUpdate(
                        COALESCE(b.props_map, map()),
                        mapFilter(
                            (k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k),
                            COALESCE(so.set_once_map, map())
                        )
                    )
                )
            ) as calculated_person_properties
        FROM tmp_events_window t
        ASOF LEFT JOIN tmp_set_checkpoints c 
            ON t.person_id = c.person_id 
            AND t.timestamp >= c.checkpoint_ts
            AND c.team_id = {team_id}
        LEFT JOIN base_props b ON t.person_id = b.person_id
        LEFT JOIN set_once_per_person so ON t.person_id = so.person_id
        WHERE t.team_id = {team_id}

        SETTINGS 
            max_execution_time = 3600, 
            allow_experimental_analyzer = 1
    """


# ============================================================================
# Step 4: Update events
# ============================================================================


def update_events_sql(team_id: int) -> str:
    """SQL to update sharded_events with calculated person_properties."""
    return f"""
        ALTER TABLE sharded_events
        UPDATE person_properties = tmp.calculated_person_properties
        FROM tmp_event_person_props_reconciliation AS tmp
        WHERE sharded_events.team_id = {team_id}
          AND sharded_events.uuid = tmp.uuid
          AND tmp.team_id = {team_id}
        SETTINGS mutations_sync = 0
    """


# ============================================================================
# Dagster ops
# ============================================================================


@dagster.op
def create_temp_tables(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """Create all temporary tables."""
    from posthog.clickhouse.client import sync_execute

    context.log.info("Creating temp tables")
    sync_execute(create_events_window_table_sql())
    sync_execute(create_checkpoints_table_sql())
    sync_execute(create_results_table_sql())


@dagster.op
def drop_temp_tables(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    _upstream: list,
) -> None:
    """Drop all temporary tables."""
    from posthog.clickhouse.client import sync_execute

    context.log.info("Dropping temp tables")
    sync_execute(drop_events_window_table_sql())
    sync_execute(drop_checkpoints_table_sql())
    sync_execute(drop_results_table_sql())


@dagster.op
def get_team_ids(
    context: dagster.OpExecutionContext,
    config: EventPersonPropertiesReconciliationConfig,
) -> list[int]:
    """Get list of team IDs to process."""
    from posthog.clickhouse.client import sync_execute

    if config.team_ids:
        context.log.info(f"Using configured team_ids: {config.team_ids}")
        return config.team_ids

    query = """
        SELECT DISTINCT team_id
        FROM events
        WHERE timestamp >= %(bug_window_start)s
          AND timestamp <= %(bug_window_end)s
          AND (JSONHas(properties, '$set') OR JSONHas(properties, '$set_once'))
        ORDER BY team_id
    """
    results = sync_execute(
        query,
        {"bug_window_start": config.bug_window_start, "bug_window_end": config.bug_window_end},
    )
    team_ids = [int(row[0]) for row in results]
    context.log.info(f"Found {len(team_ids)} teams with property events")
    return team_ids


@dagster.op(out=dagster.DynamicOut(int))
def create_team_chunks(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
    _temp_tables_created: None,
):
    """Create dynamic outputs for each team."""
    for team_id in team_ids:
        yield dagster.DynamicOutput(value=team_id, mapping_key=f"team_{team_id}")


@dagster.op
def process_team(
    context: dagster.OpExecutionContext,
    config: EventPersonPropertiesReconciliationConfig,
    team_id: int,
) -> int:
    """
    Process a single team:
    1. Single scan of events → tmp_events_window
    2. Compute checkpoints from temp table
    3. ASOF JOIN to assign states
    """
    from posthog.clickhouse.client import sync_execute

    context.log.info(f"Processing team_id={team_id}: scanning events into temp table")
    sync_execute(populate_events_window_sql(team_id, config.bug_window_start, config.bug_window_end))

    context.log.info(f"Processing team_id={team_id}: computing checkpoints")
    sync_execute(populate_checkpoints_sql(team_id, config.bug_window_start))

    context.log.info(f"Processing team_id={team_id}: ASOF JOIN for final results")
    sync_execute(populate_results_sql(team_id, config.bug_window_start))

    context.log.info(f"Completed processing team_id={team_id}")
    return team_id


@dagster.op
def update_events_for_team(
    context: dagster.OpExecutionContext,
    team_id: int,
) -> dict:
    """Update sharded_events with calculated person_properties."""
    from posthog.clickhouse.client import sync_execute

    context.log.info(f"Updating events for team_id={team_id}")
    sync_execute(update_events_sql(team_id))

    context.log.info(f"Started mutation for team_id={team_id}")
    return {"team_id": team_id, "status": "mutation_started"}


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=executor_def,
)
def event_person_properties_reconciliation_job():
    """
    Reconcile event person_properties that were incorrectly written during bug window.
    
    Flow:
    1. Create temp tables
    2. For each team:
       a. Single scan of events → tmp_events_window (THE ONLY events read)
       b. Compute checkpoints from temp table
       c. ASOF JOIN to assign states
    3. For each team: run ALTER TABLE UPDATE
    4. Drop temp tables
    """
    team_ids = get_team_ids()
    temp_tables_created = create_temp_tables()
    chunks = create_team_chunks(team_ids, temp_tables_created)

    update_results = chunks.map(lambda chunk: update_events_for_team(process_team(chunk)))

    drop_temp_tables(update_results.collect())
