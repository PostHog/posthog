from string import Template

SELECT_FROM_PERSONS_VIEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

# This is an updated version of the view that we will use going forward
# We will migrate each batch export destination over one at a time to migitate
# risk, and once this is done we can clean this up.
SELECT_FROM_PERSONS_VIEW_NEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

SELECT_FROM_PERSONS_VIEW_BACKFILL = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export_backfill(
        team_id={team_id},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

# This is an updated version of the view that we will use going forward
# We will migrate each batch export destination over one at a time to migitate
# risk, and once this is done we can clean this up.
SELECT_FROM_PERSONS_VIEW_BACKFILL_NEW = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at
FROM
    persons_batch_export_backfill(
        team_id={team_id},
        interval_end={interval_end}
    ) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

SELECT_FROM_EVENTS_VIEW = Template(
    """
SELECT
    $fields
FROM
    events_batch_export(
        team_id={team_id},
        lookback_days={lookback_days},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000
"""
)

SELECT_FROM_EVENTS_VIEW_RECENT = Template(
    """
SELECT
    $fields
FROM
    events_batch_export_recent(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=1
"""
)

SELECT_FROM_EVENTS_VIEW_RECENT_DISTRIBUTED = Template(
    """
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(distributed_events_recent.distinct_id), cityHash64(distributed_events_recent.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        inserted_at AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        distributed_events_recent
    PREWHERE
        distributed_events_recent.inserted_at >= {{interval_start:DateTime64}}
        AND distributed_events_recent.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
)
FORMAT ArrowStream
SETTINGS
    optimize_aggregation_in_order=1,
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0
"""
)


SELECT_FROM_EVENTS_VIEW_UNBOUNDED = Template(
    """
SELECT
    $fields
FROM
    events_batch_export_unbounded(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000
"""
)

SELECT_FROM_EVENTS_VIEW_BACKFILL = Template(
    """
SELECT
    $fields
FROM
    events_batch_export_backfill(
        team_id={team_id},
        interval_start={interval_start},
        interval_end={interval_end},
        include_events={include_events}::Array(String),
        exclude_events={exclude_events}::Array(String)
    ) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000
"""
)
