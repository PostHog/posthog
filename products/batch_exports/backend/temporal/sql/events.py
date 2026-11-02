"""SQL for the events batch export model."""

from string import Template

from posthog.hogql.printer.events_json_document import event_document_sql, person_document_sql

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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64} - INTERVAL {lookback_days:Int32} DAY
        AND events.timestamp < {interval_end:DateTime64} + INTERVAL 1 DAY
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
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


EXPORT_TO_S3_FROM_EVENTS = Template(
    """
INSERT INTO FUNCTION $s3_function
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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64} - INTERVAL {lookback_days:Int32} DAY
        AND events.timestamp < {interval_end:DateTime64} + INTERVAL 1 DAY
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
"""
)


SELECT_FROM_EVENTS_WORKFLOWS = Template(
    """
SELECT
    $fields
FROM events
    PREWHERE
        COALESCE(events.timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
        $filters
FORMAT ArrowStream
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""
)


EXPORT_TO_S3_FROM_EVENTS_WORKFLOWS = Template(
    """
INSERT INTO FUNCTION $s3_function
SELECT
    $fields
FROM
    events
WHERE
    team_id = {team_id:Int64}
    AND events.timestamp >= {interval_start:DateTime64}
    AND events.timestamp < {interval_end:DateTime64}
    AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
    AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    $filters
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
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
        events_recent.inserted_at >= {interval_start:DateTime64}
        AND events_recent.inserted_at < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
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


EXPORT_TO_S3_FROM_EVENTS_RECENT = Template(
    """
INSERT INTO FUNCTION $s3_function
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
        events_recent.inserted_at >= {interval_start:DateTime64}
        AND events_recent.inserted_at < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
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
        distributed_events_recent.inserted_at >= %(interval_start)s::DateTime64
        AND distributed_events_recent.inserted_at < %(interval_end)s::DateTime64
    WHERE
        team_id = %(team_id)s::Int64
        AND (length(%(include_events)s::Array(String)) = 0 OR event IN %(include_events)s::Array(String))
        AND (length(%(exclude_events)s::Array(String)) = 0 OR event NOT IN %(exclude_events)s::Array(String))
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


EXPORT_TO_S3_FROM_DISTRIBUTED_EVENTS_RECENT = Template(
    """
INSERT INTO FUNCTION $s3_function
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
        distributed_events_recent.inserted_at >= %(interval_start)s::DateTime64
        AND distributed_events_recent.inserted_at < %(interval_end)s::DateTime64
    WHERE
        team_id = %(team_id)s::Int64
        AND (length(%(include_events)s::Array(String)) = 0 OR event IN %(include_events)s::Array(String))
        AND (length(%(exclude_events)s::Array(String)) = 0 OR event NOT IN %(exclude_events)s::Array(String))
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
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


EXPORT_TO_S3_FROM_EVENTS_UNBOUNDED = Template(
    """
INSERT INTO FUNCTION $s3_function
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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
        $filters
) AS events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
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
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64}
        AND events.timestamp < {interval_end:DateTime64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
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


EXPORT_TO_S3_FROM_EVENTS_BACKFILL = Template(
    """
INSERT INTO FUNCTION $s3_function
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
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64}
        AND events.timestamp < {interval_end:DateTime64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
        $filters
) as events
SETTINGS
    -- This is half of configured MAX_MEMORY_USAGE for batch exports.
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment=%(log_comment)s
"""
)


EVENT_COUNT_BY_INTERVAL = """
SELECT
    toStartOfInterval(_inserted_at, INTERVAL %(interval)s) AS interval_start,
    interval_start + INTERVAL %(interval)s AS interval_end,
    COUNT(*) as total_count
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events_recent.distinct_id), cityHash64(events_recent.uuid))
        inserted_at AS _inserted_at
    FROM
        events_recent
    PREWHERE
        events_recent.inserted_at >= %(overall_interval_start)s::DateTime64
        AND events_recent.inserted_at < %(overall_interval_end)s::DateTime64
    WHERE
        team_id = %(team_id)s::Int64
        AND (length(%(include_events)s::Array(String)) = 0 OR event IN %(include_events)s::Array(String))
        AND (length(%(exclude_events)s::Array(String)) = 0 OR event NOT IN %(exclude_events)s::Array(String))
)
GROUP BY interval_start
ORDER BY interval_start ASC
SETTINGS
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1
"""


# `toJSONString` prints a stored dotted key as `a%2Eb` unless the query sets `json_type_escape_dots_in_keys`,
# which is why the native query's SETTINGS carry it.
_PROPERTIES_DOCUMENT = event_document_sql("properties", "temporary_properties", "properties.`$feature_flags`")
_PERSON_PROPERTIES_DOCUMENT = person_document_sql("person_properties")
SERIALIZED_EVENTS_JSON_SOURCE = """(
    SELECT * REPLACE (
        toString(uuid) AS uuid,
        toString(person_id) AS person_id,
        __PROPERTIES_DOCUMENT__ AS properties,
        __PERSON_PROPERTIES_DOCUMENT__ AS person_properties
    ),
        nullIf(toJSONString(temporary_properties.^`$set`), '{}') AS set,
        nullIf(toJSONString(temporary_properties.^`$set_once`), '{}') AS set_once,
        nullIf(toJSONString(temporary_properties.^`$unset`), '[]') AS unset,
        nullIf(toJSONString(temporary_properties.^`$group_set`), '{}') AS group_set
    FROM events_json
)""".replace("__PROPERTIES_DOCUMENT__", _PROPERTIES_DOCUMENT).replace(
    "__PERSON_PROPERTIES_DOCUMENT__", _PERSON_PROPERTIES_DOCUMENT
)


def native_events_export_query(
    fields: str,
    filters: str = "",
    *,
    order: str = "",
    s3_function: str | None = None,
) -> str:
    return f"""
{"INSERT INTO FUNCTION " + s3_function if s3_function else ""}
SELECT {fields}
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        *, timestamp AS _inserted_at
    FROM {SERIALIZED_EVENTS_JSON_SOURCE} AS events
    WHERE team_id = {{team_id:Int64}}
        AND (%(interval_start)s::Nullable(DateTime64) IS NULL OR timestamp >= %(interval_start)s::Nullable(DateTime64))
        AND timestamp < {{interval_end:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
        {"AND " + filters if filters else ""}
    {order}
) AS events
{"" if s3_function else "FORMAT ArrowStream"}
SETTINGS
    max_bytes_before_external_sort=50000000000,
    max_replica_delay_for_distributed_queries=60,
    fallback_to_stale_replicas_for_distributed_queries=0,
    optimize_aggregation_in_order=1,
    json_type_escape_dots_in_keys=1,
    output_format_json_escape_forward_slashes=0
{", log_comment=%(log_comment)s" if s3_function else ""}
"""
