"""SQL for the events batch export model."""

import re
import typing
from collections.abc import Sequence
from string import Template

from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string
from posthog.hogql.printer.events_json_document import person_document_sql, stored_properties_document_sql

from posthog.clickhouse.events_json import (
    EVENTS_JSON_INSERT_SETTINGS,
    EVENTS_JSON_RECENT_TABLE,
    PERMANENT_SDK_DEBUG_PROPERTIES,
    TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX,
    TEMPORARY_EVENT_PROPERTY_ROOTS,
    TEMPORARY_PROPERTIES_JSON_TYPE,
)
from posthog.models.event.sql import (
    EVENTS_JSON_ELEMENTS_COLUMNS,
    EVENTS_PROPERTIES_JSON_TYPE,
    PERSON_PROPERTIES_JSON_TYPE,
)

if typing.TYPE_CHECKING:
    from products.batch_exports.backend.service import BatchExportField

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


def build_event_count_by_interval_query(table: str, *, includes_feature_flag_called: bool = True) -> str:
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


EVENT_COUNT_BY_INTERVAL = build_event_count_by_interval_query("events_recent")


# The native table exports `properties` and `person_properties` in their stored shape, built member by member the
# way a HogQL read of the whole document builds them. Unlike the legacy tables:
# - flags are sent in one `$feature_flags` map, which is left out when the event has no flags.
# - temporary properties, such as `$set`, follow the other members of `properties`, as `events_json_recent` stores
#   them. ClickHouse clears them from `events_json` 60 days after an event is inserted. The legacy `set`, `set_once`,
#   `unset` and `group_set` fields are always empty.
# `toJSONString` prints a stored dotted key as `a%2Eb` unless the query sets `json_type_escape_dots_in_keys`, which is
# why the native query's SETTINGS carry it.
_EMPTY_TEMPORARY_PROPERTY_FIELDS = dict.fromkeys(
    ("set", "set_once", "unset", "group_set"), "CAST(NULL, 'Nullable(String)')"
)
_NATIVE_EVENTS_FIELD_EXPRESSIONS = {
    "properties": stored_properties_document_sql("events.properties", "events.temporary_properties"),
    "person_properties": person_document_sql("events.person_properties"),
    **_EMPTY_TEMPORARY_PROPERTY_FIELDS,
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
    select = _select_fields(fields, _NATIVE_EVENTS_FIELD_EXPRESSIONS)
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


def _select_fields(fields: Sequence["BatchExportField"], replacements: dict[str, str]) -> str:
    return ", ".join(
        f"{replacements.get(field['expression'], field['expression'])} AS {field['alias']}" for field in fields
    )


# `events_json_recent` keeps the export's own `properties` and `person_properties` documents as text, so the export
# sends them as stored. These columns hold the stored text when the query also reads the typed columns.
_STORED_DOCUMENT_COLUMNS = {
    "properties": "_stored_properties",
    "person_properties": "_stored_person_properties",
}
# Columns that are typed JSON in `events_json` but are text (or absent) in `events_json_recent`. Filters and custom
# fields printed for the new events schema read them with JSON subcolumn syntax, which fails on text.
_TYPED_COLUMN_REFERENCE = re.compile(r"\b(?:properties|person_properties|temporary_properties|elements_chain_\w+)\b")


def _reads_typed_columns(fields: Sequence["BatchExportField"], filters: str) -> bool:
    return bool(filters) or any(
        field["expression"] not in _NATIVE_EVENTS_FIELD_EXPRESSIONS
        and _TYPED_COLUMN_REFERENCE.search(field["expression"]) is not None
        for field in fields
    )


def _parse_materialized_columns(columns_sql: str) -> list[str]:
    """`<expression> AS <name>` for each `, <name> <type> MATERIALIZED <expression>` line of a column list."""
    selected = []
    for line in columns_sql.strip().splitlines():
        name, definition = line.strip().removeprefix(",").strip().split(" ", 1)
        expression = definition.split(" MATERIALIZED ", 1)[1]
        selected.append(f"{expression} AS {name}")
    return selected


def _build_temporary_property_skip_clauses() -> str:
    """JSON type `SKIP` clauses for the paths that `is_temporary_event_property` puts in `temporary_properties`.

    RE2 has no lookahead, so the pattern for the `$sdk_debug_` prefix lists every way a root key can differ from the
    permanent key: it ends early, it has a different character, or it continues past the permanent key's name. A
    root key that equals the permanent key ends the path or is followed by a nested path's `.`. The pattern handles
    one permanent key, so the unpacking below fails at import when a second one is added.
    """
    (permanent_key,) = PERMANENT_SDK_DEBUG_PROPERTIES
    permanent_suffix = permanent_key.removeprefix(TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX)
    differs_from_permanent = [
        f"{re.escape(permanent_suffix[:index])}(?:$|[^{re.escape(character)}])"
        for index, character in enumerate(permanent_suffix)
    ]
    differs_from_permanent.append(f"{re.escape(permanent_suffix)}[^.]")
    prefix_pattern = f"^{re.escape(TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX)}(?:{'|'.join(differs_from_permanent)})"
    roots = (f"SKIP {escape_clickhouse_identifier(root)}" for root in sorted(TEMPORARY_EVENT_PROPERTY_ROOTS))
    return ", ".join([*roots, f"SKIP REGEXP {escape_clickhouse_string(prefix_pattern)}"])


_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE = (
    f"{EVENTS_PROPERTIES_JSON_TYPE().removesuffix(')')}, {_build_temporary_property_skip_clauses()})"
)


def _build_typed_events_json_recent_source(table: str) -> str:
    """`events_json_recent` with its document columns converted to the column types of `events_json`.

    The stored documents leave out the declared defaults that `events_json` reads back, and a declared path converts
    back to its default when it is absent, so filters and fields match what they match on `events_json`. The stored
    `properties` document also carries the temporary properties, which `events_json` keeps in `temporary_properties`
    only, so the conversion skips them there. The `elements_chain_*` columns are materialized in `events_json` only,
    so this computes them the same way.
    """
    elements_chain_columns = ",\n        ".join(_parse_materialized_columns(EVENTS_JSON_ELEMENTS_COLUMNS))
    return f"""(
    SELECT
        * REPLACE (
            CAST(properties, {escape_clickhouse_string(_EVENTS_PROPERTIES_WITHOUT_TEMPORARY_JSON_TYPE)}) AS properties,
            CAST(person_properties, '{PERSON_PROPERTIES_JSON_TYPE()}') AS person_properties,
            CAST(temporary_properties, '{TEMPORARY_PROPERTIES_JSON_TYPE}') AS temporary_properties
        ),
        {table}.properties AS {_STORED_DOCUMENT_COLUMNS["properties"]},
        {table}.person_properties AS {_STORED_DOCUMENT_COLUMNS["person_properties"]},
        {elements_chain_columns}
    FROM {table}
    WHERE team_id = %(team_id)s::Int64
        AND inserted_at >= %(interval_start)s::DateTime64
        AND inserted_at < %(interval_end)s::DateTime64
)"""


def native_recent_events_export_query(
    fields: Sequence["BatchExportField"],
    filters: str = "",
    *,
    is_5_min_batch_export: bool,
    includes_feature_flag_called: bool,
    order: str = "",
    s3_function: str | None = None,
) -> str:
    """The export query for `events_json_recent`, which recent runs of a team on the new events schema read.

    `filters` and any custom field expressions must be printed for the new events schema, as for
    `native_events_export_query`. They read typed JSON columns, so when there are any the query converts the stored
    text back to those types. That conversion parses every row again, so a query without them sends the stored text
    without reading it.
    """
    reads_typed_columns = _reads_typed_columns(fields, filters)
    replacements = _EMPTY_TEMPORARY_PROPERTY_FIELDS | (_STORED_DOCUMENT_COLUMNS if reads_typed_columns else {})
    source = (
        _build_typed_events_json_recent_source(EVENTS_JSON_RECENT_TABLE)
        if reads_typed_columns
        else EVENTS_JSON_RECENT_TABLE
    )
    # A 5-minute run reads straight after the data interval ends, so it accepts only fully replicated rows. Other
    # recent runs accept up to a minute of replication lag, and fail rather than read a replica that is further behind.
    replica_settings = (
        "max_replica_delay_for_distributed_queries=1"
        if is_5_min_batch_export
        else "max_replica_delay_for_distributed_queries=60,\n    fallback_to_stale_replicas_for_distributed_queries=0"
    )
    return f"""
{"INSERT INTO FUNCTION " + s3_function if s3_function else ""}
SELECT {_select_fields(fields, replacements)}
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
    {replica_settings},
    optimize_aggregation_in_order=1,
    {EVENTS_JSON_INSERT_SETTINGS},
    output_format_json_escape_forward_slashes=0
{", log_comment=%(log_comment)s" if s3_function else ""}
"""
