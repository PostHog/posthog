"""SQL for the events batch export model."""

import typing
from collections.abc import Mapping, Sequence
from string import Template

from posthog.hogql.printer.events_json_document import (
    EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
    json_member_pairs_sql,
    person_document_sql,
)

from posthog.clickhouse.events_json import EVENTS_JSON_INSERT_SETTINGS, EVENTS_JSON_RECENT_TABLE

from products.batch_exports.backend.temporal.sql.typed_events_json_recent import (
    STORED_DOCUMENT_FIELD_EXPRESSIONS,
    STORED_TEMPORARY_PROPERTIES_COLUMN,
    build_typed_events_json_recent_source,
)

if typing.TYPE_CHECKING:
    from products.batch_exports.backend.service import BatchExportField

SELECT_FROM_EVENTS_VIEW = Template(
    """
SELECT
    $fields
FROM (
    WITH JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties
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
        nullIf(extracted_properties.1, '') AS set,
        nullIf(extracted_properties.2, '') AS set_once,
        nullIf(extracted_properties.3, '') AS ip
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
    WITH JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties
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
        nullIf(extracted_properties.1, '') AS set,
        nullIf(extracted_properties.2, '') AS set_once,
        nullIf(extracted_properties.3, '') AS ip
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


# Workflows exports send no `ip` field, so the two workflows templates select no `ip` column, unlike the other legacy
# templates.
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
    SELECT DISTINCT ON (team_id, event, distinct_id_hash, uuid_hash)
        team_id,
        timestamp,
        event,
        distinct_id,
        uuid,
        _inserted_at,
        created_at,
        elements_chain,
        person_id,
        properties,
        person_properties,
        set,
        set_once,
        ip
    FROM (
        -- ClickHouse runs the dedup on one thread and evaluates its SELECT list after it. This subquery is below
        -- the dedup, so the parse of `properties` runs on every read thread.
        SELECT
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
            JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties,
            nullIf(extracted_properties.1, '') AS set,
            nullIf(extracted_properties.2, '') AS set_once,
            nullIf(extracted_properties.3, '') AS ip,
            cityHash64(events_recent.distinct_id) AS distinct_id_hash,
            cityHash64(events_recent.uuid) AS uuid_hash
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
    )
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
    SELECT DISTINCT ON (team_id, event, distinct_id_hash, uuid_hash)
        team_id,
        timestamp,
        event,
        distinct_id,
        uuid,
        _inserted_at,
        created_at,
        elements_chain,
        person_id,
        properties,
        person_properties,
        set,
        set_once,
        ip
    FROM (
        -- ClickHouse runs the dedup on one thread and evaluates its SELECT list after it. This subquery is below
        -- the dedup, so the parse of `properties` runs on every read thread.
        SELECT
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
            JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties,
            nullIf(extracted_properties.1, '') AS set,
            nullIf(extracted_properties.2, '') AS set_once,
            nullIf(extracted_properties.3, '') AS ip,
            cityHash64(events_recent.distinct_id) AS distinct_id_hash,
            cityHash64(events_recent.uuid) AS uuid_hash
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
    )
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
    SELECT DISTINCT ON (team_id, event, distinct_id_hash, uuid_hash)
        team_id,
        timestamp,
        event,
        distinct_id,
        uuid,
        _inserted_at,
        created_at,
        elements_chain,
        person_id,
        properties,
        person_properties,
        set,
        set_once,
        ip
    FROM (
        -- ClickHouse runs the dedup on one thread and evaluates its SELECT list after it. This subquery is below
        -- the dedup, so the parse of `properties` runs on every read thread.
        SELECT
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
            JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties,
            nullIf(extracted_properties.1, '') AS set,
            nullIf(extracted_properties.2, '') AS set_once,
            nullIf(extracted_properties.3, '') AS ip,
            cityHash64(distributed_events_recent.distinct_id) AS distinct_id_hash,
            cityHash64(distributed_events_recent.uuid) AS uuid_hash
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
    )
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
    SELECT DISTINCT ON (team_id, event, distinct_id_hash, uuid_hash)
        team_id,
        timestamp,
        event,
        distinct_id,
        uuid,
        _inserted_at,
        created_at,
        elements_chain,
        person_id,
        properties,
        person_properties,
        set,
        set_once,
        ip
    FROM (
        -- ClickHouse runs the dedup on one thread and evaluates its SELECT list after it. This subquery is below
        -- the dedup, so the parse of `properties` runs on every read thread.
        SELECT
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
            JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties,
            nullIf(extracted_properties.1, '') AS set,
            nullIf(extracted_properties.2, '') AS set_once,
            nullIf(extracted_properties.3, '') AS ip,
            cityHash64(distributed_events_recent.distinct_id) AS distinct_id_hash,
            cityHash64(distributed_events_recent.uuid) AS uuid_hash
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
    )
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


SELECT_FROM_EVENTS_VIEW_BACKFILL = Template(
    """
SELECT
    $fields
FROM (
    WITH JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties
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
        nullIf(extracted_properties.1, '') AS set,
        nullIf(extracted_properties.2, '') AS set_once,
        nullIf(extracted_properties.3, '') AS ip
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
    WITH JSONExtract(ifNull(properties, ''), 'Tuple(`$$set` String, `$$set_once` String, `$$ip` String)') AS extracted_properties
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
        nullIf(extracted_properties.1, '') AS set,
        nullIf(extracted_properties.2, '') AS set_once,
        nullIf(extracted_properties.3, '') AS ip
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


def build_event_count_by_interval_query(table: str, *, includes_feature_flag_called: bool) -> str:
    """Count the events a 5-minute export of `table` reads, per interval, for monitoring."""
    feature_flag_called_filter = "" if includes_feature_flag_called else "AND event != '$feature_flag_called'"
    return """
SELECT
    toStartOfInterval(_inserted_at, INTERVAL %(interval)s) AS interval_start,
    interval_start + INTERVAL %(interval)s AS interval_end,
    COUNT(*) as total_count
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64({table}.distinct_id), cityHash64({table}.uuid))
        inserted_at AS _inserted_at
    FROM
        {table}
    PREWHERE
        {table}.inserted_at >= %(overall_interval_start)s::DateTime64
        AND {table}.inserted_at < %(overall_interval_end)s::DateTime64
    WHERE
        team_id = %(team_id)s::Int64
        AND (length(%(include_events)s::Array(String)) = 0 OR event IN %(include_events)s::Array(String))
        AND (length(%(exclude_events)s::Array(String)) = 0 OR event NOT IN %(exclude_events)s::Array(String))
        {feature_flag_called_filter}
)
GROUP BY interval_start
ORDER BY interval_start ASC
SETTINGS
    max_replica_delay_for_distributed_queries=1,
    optimize_aggregation_in_order=1
""".format(table=table, feature_flag_called_filter=feature_flag_called_filter)


EVENT_COUNT_BY_INTERVAL = build_event_count_by_interval_query("events_recent", includes_feature_flag_called=True)


def _build_temporary_property_fields(temporary_properties_text: str) -> dict[str, str]:
    """The legacy `set`, `set_once`, `unset` and `group_set` fields, from the temporary properties as JSON text.

    `set` and `set_once` use the expression the legacy queries apply to `properties`. ClickHouse's `JSONExtractString`
    returns an object member as its JSON text, so the fields carry the same text as before.
    """
    return {
        "set": f"nullIf(JSONExtractString({temporary_properties_text}, '$set'), '')",
        "set_once": f"nullIf(JSONExtractString({temporary_properties_text}, '$set_once'), '')",
        **dict.fromkeys(("unset", "group_set"), "CAST(NULL, 'Nullable(String)')"),
    }


# The events tables store no `ip` column, so these replacements build it from `$ip`. On typed `properties`, the
# `String` variant is NULL when `$ip` is not a string, which matches `JSONExtractString` on the stored text.
# On `events_json_recent` this parses `properties` once per row only for `ip`, so a future change could drop the `ip`
# column from the destinations that export it to save that work.
_TYPED_IP_FIELD_EXPRESSIONS = {"ip": "nullIf(events.properties.`$ip`.:String, '')"}
_STORED_IP_FIELD_EXPRESSIONS = {"ip": "nullIf(JSONExtractString(events.properties, '$ip'), '')"}


def _build_properties_document_sql(properties: str, temporary_properties: str) -> str:
    """The `properties` column as document text in its stored shape, with the temporary properties after the others."""
    pairs = (
        json_member_pairs_sql(
            properties,
            exclude_empty_key="$feature_flags",
            declared_string_paths=EVENTS_PROPERTIES_DECLARED_STRING_PATHS,
        ),
        json_member_pairs_sql(temporary_properties),
    )
    return f"concat('{{', arrayStringConcat(arrayConcat({', '.join(pairs)}), ','), '}}')"


# The native table exports `properties` and `person_properties` in their stored shape, built member by member the
# way a HogQL read of the whole document builds them. Unlike the legacy tables:
# - flags are sent in one `$feature_flags` map, which is left out when the event has no flags.
# - temporary properties, such as `$set`, follow the other members of `properties`, as `events_json_recent` stores
#   them. ClickHouse clears them from `events_json` 60 days after an event is inserted.
# - the legacy `set` and `set_once` fields are read from the temporary properties, which hold `$set` and `$set_once`.
#   `unset` and `group_set` are always empty.
# `toJSONString` prints a stored dotted key as `a%2Eb` unless the query sets `json_type_escape_dots_in_keys`, which is
# why the native query's SETTINGS carry it.
# `events_json_recent` stores the same `properties` documents, written at insert time by the export cleaner, so a change
# here needs the matching change in `clickhouse-udfs/util/cmd/json_clean_posthog_event_properties_udf/export.go`.
_NATIVE_EVENTS_FIELD_EXPRESSIONS = {
    "properties": _build_properties_document_sql("events.properties", "events.temporary_properties"),
    "person_properties": person_document_sql("events.person_properties"),
    **_build_temporary_property_fields("toJSONString(events.temporary_properties)"),
    **_TYPED_IP_FIELD_EXPRESSIONS,
}


def native_events_export_query(
    fields: Sequence["BatchExportField"],
    filters: str = "",
    *,
    order: str = "",
    s3_function: str | None = None,
) -> str:
    """The export query for the native events table.

    `filters` and any custom field expressions must be printed for the new events schema. They read the typed
    `events.properties` and `events.person_properties` columns, which the query turns into text only for the export's
    own `properties` and `person_properties` fields.
    """
    select = build_select_list(fields, _NATIVE_EVENTS_FIELD_EXPRESSIONS)
    return f"""
{"INSERT INTO FUNCTION " + s3_function if s3_function else ""}
SELECT {select}
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        * REPLACE (toString(uuid) AS uuid, toString(person_id) AS person_id), timestamp AS _inserted_at
    FROM events_json AS events
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


def build_select_list(fields: Sequence["BatchExportField"], replacements: Mapping[str, str] | None = None) -> str:
    """Each field's expression, or its replacement in `replacements`, aliased to the field's alias."""
    replacements = replacements or {}
    return ", ".join(
        f"{replacements.get(field['expression'], field['expression'])} AS {field['alias']}" for field in fields
    )


def native_recent_events_export_query(
    fields: Sequence["BatchExportField"],
    filters: str = "",
    *,
    includes_feature_flag_called: bool,
    reads_typed_columns: bool,
    order: str = "",
    s3_function: str | None = None,
) -> str:
    """The export query for `events_json_recent`, which runs on the new events schema read for the ranges it holds.

    The query sends the stored `properties` and `person_properties` text as it is. `filters` and any custom field
    expressions must be printed for the new events schema, as for `native_events_export_query`, and they read typed
    JSON columns. The caller sets `reads_typed_columns` when they do, and the query then reads the table through
    `typed_events_json_recent`, which re-parses every row. The stored text has no typed subcolumns, so typed syntax
    on the plain read fails.
    """
    if reads_typed_columns:
        source = build_typed_events_json_recent_source()
        replacements = (
            STORED_DOCUMENT_FIELD_EXPRESSIONS
            | _build_temporary_property_fields(f"events.{STORED_TEMPORARY_PROPERTIES_COLUMN}")
            | _TYPED_IP_FIELD_EXPRESSIONS
        )
    else:
        source = EVENTS_JSON_RECENT_TABLE
        replacements = _build_temporary_property_fields("events.temporary_properties") | _STORED_IP_FIELD_EXPRESSIONS
    return f"""
{"INSERT INTO FUNCTION " + s3_function if s3_function else ""}
SELECT {build_select_list(fields, replacements)}
FROM (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        * REPLACE (toString(uuid) AS uuid, toString(person_id) AS person_id), inserted_at AS _inserted_at
    FROM {source} AS events
    WHERE team_id = %(team_id)s::Int64
        AND inserted_at >= %(interval_start)s::DateTime64
        AND inserted_at < %(interval_end)s::DateTime64
        AND (length(%(include_events)s::Array(String)) = 0 OR event IN %(include_events)s::Array(String))
        AND (length(%(exclude_events)s::Array(String)) = 0 OR event NOT IN %(exclude_events)s::Array(String))
        {"" if includes_feature_flag_called else "AND event != '$feature_flag_called'"}
        {"AND " + filters if filters else ""}
    {order}
) AS events
{"" if s3_function else "FORMAT ArrowStream"}
SETTINGS
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    {EVENTS_JSON_INSERT_SETTINGS},
    output_format_json_escape_forward_slashes=0
{", log_comment=%(log_comment)s" if s3_function else ""}
"""
