from string import Template

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.parser import parse_expr

SELECT_FROM_PERSONS = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at,
    persons.is_deleted AS is_deleted
FROM (
    with new_persons as (
        select
            id,
            max(version) as version,
            argMax(_timestamp, person.version) AS _timestamp2
        from
            person
        where
            team_id = {team_id}::Int64
            and id in (
                select
                    id
                from
                    person
                where
                    team_id = {team_id}::Int64
                    and _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        group by
            id
        having
            (
                _timestamp2 >= {interval_start}::DateTime64
                AND _timestamp2 < {interval_end}::DateTime64
            )
    ),
    new_distinct_ids as (
        SELECT
            argMax(person_id, person_distinct_id2.version) as person_id
        from
            person_distinct_id2
        where
            team_id = {team_id}::Int64
            and distinct_id in (
                select
                    distinct_id
                from
                    person_distinct_id2
                where
                    team_id = {team_id}::Int64
                    and _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        group by
            distinct_id
        having
            (
                argMax(_timestamp, person_distinct_id2.version) >= {interval_start}::DateTime64
                AND argMax(_timestamp, person_distinct_id2.version) < {interval_end}::DateTime64
            )
    ),
    all_new_persons as (
        select
            id,
            version
        from
            new_persons
        UNION
        ALL
        select
            id,
            max(version)
        from
            person
        where
            team_id = {team_id}::Int64
            and id in new_distinct_ids
        group by
            id
    )
    select
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        toBool(p.is_deleted) AS is_deleted,
        multiIf(
            (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            ),
            pd._timestamp,
            (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    from
        person p
        INNER JOIN (
            SELECT
                distinct_id,
                max(version) AS version,
                argMax(person_id, person_distinct_id2.version) AS person_id2,
                argMax(_timestamp, person_distinct_id2.version) AS _timestamp
            FROM
                person_distinct_id2
            WHERE
                team_id = {team_id}::Int64
                and person_id IN (
                    select
                        id
                    from
                        all_new_persons
                )
            GROUP BY
                distinct_id
        ) AS pd ON p.id = pd.person_id2
    where
        team_id = {team_id}::Int64
        and (id, version) in all_new_persons
    ORDER BY
        _inserted_at
) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""

SELECT_FROM_PERSONS_BACKFILL = """
SELECT
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS person_id,
    p.properties AS properties,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    p.created_at AS created_at,
    toBool(p.is_deleted) AS is_deleted,
    multiIf(
        pd._timestamp < {interval_end}::DateTime64
            AND NOT p._timestamp < {interval_end}::DateTime64,
        pd._timestamp,
        p._timestamp < {interval_end}::DateTime64
            AND NOT pd._timestamp < {interval_end}::DateTime64,
        p._timestamp,
        least(p._timestamp, pd._timestamp)
    ) AS _inserted_at
FROM (
    SELECT
        team_id,
        distinct_id,
        max(version) AS version,
        argMax(person_id, person_distinct_id2.version) AS person_id,
        argMax(_timestamp, person_distinct_id2.version) AS _timestamp
    FROM
        person_distinct_id2
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        distinct_id
) AS pd
INNER JOIN (
    SELECT
        team_id,
        id,
        max(version) AS version,
        argMax(properties, person.version) AS properties,
        argMax(created_at, person.version) AS created_at,
        argMax(_timestamp, person.version) AS _timestamp,
        argMax(is_deleted, person.version) AS is_deleted
    FROM
        person
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        id
) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
WHERE
    pd.team_id = {team_id}::Int64
    AND p.team_id = {team_id}::Int64
    AND (
        pd._timestamp < {interval_end}::DateTime64
        OR p._timestamp < {interval_end}::DateTime64
    )
ORDER BY
    _inserted_at
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
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}} - INTERVAL {{lookback_days:Int32}} DAY
        AND events.timestamp < {{interval_end:DateTime64}} + INTERVAL 1 DAY
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
    $order
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_EVENTS_VIEW_RECENT = Template(
    """
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid))
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
        events_recent AS events
    PREWHERE
        events_recent.inserted_at >= {{interval_start:DateTime64}}
        AND events_recent.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
    $order
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_DISTRIBUTED_EVENTS_RECENT = Template(
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
        nullIf(JSONExtractString(properties, '$$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$$set_once'), '') AS set_once
    FROM
        distributed_events_recent AS events
    PREWHERE
        distributed_events_recent.inserted_at >= {interval_start}::DateTime64
        AND distributed_events_recent.inserted_at < {interval_end}::DateTime64
    WHERE
        team_id = {team_id}::Int64
        AND (length({include_events}::Array(String)) = 0 OR event IN {include_events}::Array(String))
        AND (length({exclude_events}::Array(String)) = 0 OR event NOT IN {exclude_events}::Array(String))
        $filters
    $order
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0,
    optimize_aggregation_in_order=1
"""
)


SELECT_FROM_EVENTS_VIEW_UNBOUNDED = Template(
    """
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
    $order
) AS events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)

SELECT_FROM_EVENTS_VIEW_BACKFILL = Template(
    """
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        timestamp AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}}
        AND events.timestamp < {{interval_end:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
    $order
) as events
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)


class HogQLQueryBatchExportSettings(HogQLQuerySettings):
    optimize_aggregation_in_order: bool | None = True
    max_bytes_before_external_sort: int | None = 50000000000
    max_bytes_before_external_group_by: int | None = 50000000000


SELECT_FROM_SESSIONS_HOGQL = ast.SelectQuery(
    select=[
        parse_expr("session_id as session_id"),
        parse_expr("toString(session_id_v7) as session_id_v7"),
        parse_expr("team_id"),
        parse_expr("distinct_id as distinct_id"),
        parse_expr("$start_timestamp as start_timestamp"),
        parse_expr("$end_timestamp as end_timestamp"),
        parse_expr("$urls as urls"),
        parse_expr("$num_uniq_urls as num_uniq_urls"),
        parse_expr("$entry_current_url as entry_current_url"),
        parse_expr("$entry_pathname as entry_pathname"),
        parse_expr("$entry_hostname as entry_hostname"),
        parse_expr("$end_current_url as end_current_url"),
        parse_expr("$end_pathname as end_pathname"),
        parse_expr("$end_hostname as end_hostname"),
        parse_expr("$entry_utm_source as entry_utm_source"),
        parse_expr("$entry_utm_campaign as entry_utm_campaign"),
        parse_expr("$entry_utm_medium as entry_utm_medium"),
        parse_expr("$entry_utm_term as entry_utm_term"),
        parse_expr("$entry_utm_content as entry_utm_content"),
        parse_expr("$entry_referring_domain as entry_referring_domain"),
        parse_expr("$entry_gclid as entry_gclid"),
        parse_expr("$entry_fbclid as entry_fbclid"),
        parse_expr("$entry_gad_source as entry_gad_source"),
        parse_expr("$pageview_count as pageview_count"),
        parse_expr("$autocapture_count as autocapture_count"),
        parse_expr("$screen_count as screen_count"),
        parse_expr("$channel_type as channel_type"),
        parse_expr("$session_duration as session_duration"),
        parse_expr("duration as duration"),
        parse_expr("$is_bounce as is_bounce"),
        parse_expr("$last_external_click_url as last_external_click_url"),
        parse_expr("$page_screen_autocapture_count_up_to as page_screen_autocapture_count_up_to"),
        parse_expr("$exit_current_url as exit_current_url"),
        parse_expr("$exit_pathname as exit_pathname"),
        parse_expr("$vitals_lcp as vitals_lcp"),
        parse_expr("$end_timestamp as _inserted_at"),
        parse_expr("$entry_gclsrc as entry_gclsrc"),
        parse_expr("$entry_dclid as entry_dclid"),
        parse_expr("$entry_gbraid as entry_gbraid"),
        parse_expr("$entry_wbraid as entry_wbraid"),
        parse_expr("$entry_msclkid as entry_msclkid"),
        parse_expr("$entry_twclid as entry_twclid"),
        parse_expr("$entry_li_fat_id as entry_li_fat_id"),
        parse_expr("$entry_mc_cid as entry_mc_cid"),
        parse_expr("$entry_igshid as entry_igshid"),
        parse_expr("$entry_ttclid as entry_ttclid"),
        parse_expr("$entry__kx as entry__kx"),
        parse_expr("$entry_irclid as entry_irclid"),
    ],
    select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
    order_by=[ast.OrderExpr(expr=ast.Field(chain=["_inserted_at"]), order="ASC")],
    settings=HogQLQueryBatchExportSettings(),
)

EXPORT_TO_S3_FROM_DISTRIBUTED_EVENTS_RECENT = Template(
    """
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
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
        nullIf(JSONExtractString(properties, '$$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$$set_once'), '') AS set_once
    FROM
        distributed_events_recent AS events
    PREWHERE
        distributed_events_recent.inserted_at >= {interval_start}::DateTime64
        AND distributed_events_recent.inserted_at < {interval_end}::DateTime64
    WHERE
        team_id = {team_id}::Int64
        AND (length({include_events}::Array(String)) = 0 OR event IN {include_events}::Array(String))
        AND (length({exclude_events}::Array(String)) = 0 OR event NOT IN {exclude_events}::Array(String))
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
"""
)

EXPORT_TO_S3_FROM_EVENTS_RECENT = Template(
    """
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid))
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
        events_recent AS events
    PREWHERE
        events_recent.inserted_at >= {{interval_start:DateTime64}}
        AND events_recent.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
"""
)

EXPORT_TO_S3_FROM_EVENTS_UNBOUNDED = Template(
    """
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
"""
)

EXPORT_TO_S3_FROM_EVENTS_BACKFILL = Template(
    """
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        timestamp AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}}
        AND events.timestamp < {{interval_end:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
) as events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
"""
)

EXPORT_TO_S3_FROM_EVENTS = Template(
    """
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    $fields
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        COALESCE(events.inserted_at, events._timestamp) >= {{interval_start:DateTime64}}
        AND COALESCE(events.inserted_at, events._timestamp) < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}} - INTERVAL {{lookback_days:Int32}} DAY
        AND events.timestamp < {{interval_end:DateTime64}} + INTERVAL 1 DAY
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
"""
)

EXPORT_TO_S3_FROM_PERSONS_BACKFILL = Template("""
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS person_id,
    p.properties AS properties,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    p.created_at AS created_at,
    toBool(p.is_deleted) AS is_deleted,
    multiIf(
        pd._timestamp < {interval_end}::DateTime64
            AND NOT p._timestamp < {interval_end}::DateTime64,
        pd._timestamp,
        p._timestamp < {interval_end}::DateTime64
            AND NOT pd._timestamp < {interval_end}::DateTime64,
        p._timestamp,
        least(p._timestamp, pd._timestamp)
    ) AS _inserted_at
FROM (
    SELECT
        team_id,
        distinct_id,
        max(version) AS version,
        argMax(person_id, person_distinct_id2.version) AS person_id,
        argMax(_timestamp, person_distinct_id2.version) AS _timestamp
    FROM
        person_distinct_id2
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        distinct_id
) AS pd
INNER JOIN (
    SELECT
        team_id,
        id,
        max(version) AS version,
        argMax(properties, person.version) AS properties,
        argMax(created_at, person.version) AS created_at,
        argMax(_timestamp, person.version) AS _timestamp,
        argMax(is_deleted, person.version) AS is_deleted
    FROM
        person
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        id
) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
WHERE
    pd.team_id = {team_id}::Int64
    AND p.team_id = {team_id}::Int64
    AND (
        pd._timestamp < {interval_end}::DateTime64
        OR p._timestamp < {interval_end}::DateTime64
    )
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
""")

EXPORT_TO_S3_FROM_PERSONS = Template("""
INSERT INTO FUNCTION
   s3(
       '$s3_folder/export_{{_partition_id}}.arrow',
       '$s3_key',
       '$s3_secret',
       'ArrowStream'
    )
    PARTITION BY rand() %% $num_partitions
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at,
    persons.is_deleted AS is_deleted
FROM (
    with new_persons as (
        select
            id,
            max(version) as version,
            argMax(_timestamp, person.version) AS _timestamp2
        from
            person
        where
            team_id = {team_id}::Int64
            and id in (
                select
                    id
                from
                    person
                where
                    team_id = {team_id}::Int64
                    and _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        group by
            id
        having
            (
                _timestamp2 >= {interval_start}::DateTime64
                AND _timestamp2 < {interval_end}::DateTime64
            )
    ),
    new_distinct_ids as (
        SELECT
            argMax(person_id, person_distinct_id2.version) as person_id
        from
            person_distinct_id2
        where
            team_id = {team_id}::Int64
            and distinct_id in (
                select
                    distinct_id
                from
                    person_distinct_id2
                where
                    team_id = {team_id}::Int64
                    and _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        group by
            distinct_id
        having
            (
                argMax(_timestamp, person_distinct_id2.version) >= {interval_start}::DateTime64
                AND argMax(_timestamp, person_distinct_id2.version) < {interval_end}::DateTime64
            )
    ),
    all_new_persons as (
        select
            id,
            version
        from
            new_persons
        UNION
        ALL
        select
            id,
            max(version)
        from
            person
        where
            team_id = {team_id}::Int64
            and id in new_distinct_ids
        group by
            id
    )
    select
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        toBool(p.is_deleted) AS is_deleted,
        multiIf(
            (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            ),
            pd._timestamp,
            (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    from
        person p
        INNER JOIN (
            SELECT
                distinct_id,
                max(version) AS version,
                argMax(person_id, person_distinct_id2.version) AS person_id2,
                argMax(_timestamp, person_distinct_id2.version) AS _timestamp
            FROM
                person_distinct_id2
            WHERE
                team_id = {team_id}::Int64
                and person_id IN (
                    select
                        id
                    from
                        all_new_persons
                )
            GROUP BY
                distinct_id
        ) AS pd ON p.id = pd.person_id2
    where
        team_id = {team_id}::Int64
        and (id, version) in all_new_persons
) AS persons
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
""")
