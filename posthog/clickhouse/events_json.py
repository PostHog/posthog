"""ClickHouse schema declarations for the native-JSON events tables.

Table names, JSON subcolumn type declarations, and index DDL for the events-JSON schema.
Django-free so the HogQL engine (printer, property planner) can import these without booting
Django; posthog.models.event.sql re-exports the public names for existing callers.
"""

import re
from functools import cache

EVENTS_JSON_DATA_TABLE = "sharded_events_json"
WRITABLE_EVENTS_JSON_TABLE = "writable_events_json"
DISTRIBUTED_EVENTS_JSON_TABLE = "events_json"
KAFKA_EVENTS_NATIVE_JSON_TABLE = "kafka_events_json_native_json"
UNPARSEABLE_PROPERTIES_KEY = "$unparseable_properties"
TEMPORARY_PROPERTIES_COLUMN = "temporary_properties"

# Mirrors isTemporaryProperty in clickhouse-udfs/util/cmd/json_clean_posthog_event_properties_udf/main.go, so update both.
TEMPORARY_EVENT_PROPERTY_ROOTS = frozenset(
    {
        "$set",
        "$set_once",
        "$unset",
        "$group_set",
        "$feature_flag_request_id",
        "$debug_first_full_snapshot_timestamp",
        "$snapshot_max_depth_exceeded",
        "$sess_rec_flush_size",
        "$session_recording_remote_config",
        "$session_recording_network_payload_capture",
        "$session_recording_canvas_recording",
        "$replay_script_config",
        "$sent_at",
        "$lib_rate_limit_remaining_tokens",
        "$lib_custom_api_host",
    }
)
TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX = "$sdk_debug_"


def is_temporary_event_property(key: str) -> bool:
    """Whether the native cleaner stores this top-level event property in `temporary_properties`.

    A dotted key such as `$set.foo` is one flat key, so it matches only the prefix rule, never a root name.
    """
    return key in TEMPORARY_EVENT_PROPERTY_ROOTS or key.startswith(TEMPORARY_EVENT_PROPERTY_ROOT_PREFIX)


# Every path not declared below is a dynamic subcolumn (up to the column's max_dynamic_paths per part, then
# shared data) and keeps its JSON type. Declare only what ClickHouse cannot infer: LowCardinality
# for genuinely low-cardinality strings, the feature-flags map, the String join keys behind the
# $session_id, $window_id, and $group_N columns, and the arrays the event cleaner coerces.
EVENTS_PROPERTIES_JSON_MAX_DYNAMIC_PATHS = 1024
PERSON_PROPERTIES_JSON_MAX_DYNAMIC_PATHS = 256
TEMPORARY_PROPERTIES_JSON_TYPE = "JSON(max_dynamic_paths = 32)"
# Without the first two, ClickHouse infers Date/DateTime from date-like strings on some inserts and String on
# others. The last two keep a dotted key such as `a.b` one flat key, stored under the path name `a%2Eb`, the way the
# legacy table and HogQL property filters treat it; ClickHouse would otherwise nest it as `{"a":{"b":...}}`. A document
# that carries both spellings keeps the first value instead of failing the whole cast, and a key sent literally as
# `a%2Eb` cannot be told apart from `a.b`. Readers get the `.` back only when they set
# `json_type_escape_dots_in_keys` too (see HogQLQuerySettings).
EVENTS_JSON_INSERT_SETTINGS = (
    "input_format_try_infer_dates = 0, input_format_try_infer_datetimes = 0, "
    "json_type_escape_dots_in_keys = 1, type_json_skip_duplicated_paths = 1"
)

EVENTS_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES: dict[str, str] = {
    "$browser": "LowCardinality(String)",
    "$browser_language": "LowCardinality(String)",
    "$browser_version": "LowCardinality(String)",
    "$config_defaults": "LowCardinality(String)",
    "$device_type": "LowCardinality(String)",
    "$exception_functions": "Array(String)",
    "$exception_list": "Array(JSON(max_dynamic_paths = 0, type String, value String))",
    "$exception_sources": "Array(String)",
    "$exception_types": "Array(String)",
    "$exception_values": "Array(String)",
    "$feature_flags": "Map(LowCardinality(String), LowCardinality(String))",
    "$geoip_city_name": "LowCardinality(String)",
    "$geoip_continent_code": "LowCardinality(String)",
    "$geoip_continent_name": "LowCardinality(String)",
    "$geoip_country_code": "LowCardinality(String)",
    "$geoip_country_name": "LowCardinality(String)",
    "$geoip_subdivision_1_name": "LowCardinality(String)",
    "$geoip_time_zone": "LowCardinality(String)",
    "$group_0": "String",
    "$group_1": "String",
    "$group_2": "String",
    "$group_3": "String",
    "$group_4": "String",
    "$lib": "LowCardinality(String)",
    "$lib_version": "LowCardinality(String)",
    "$mcp_listed_tool_names": "Array(String)",
    "$os": "LowCardinality(String)",
    "$os_version": "LowCardinality(String)",
    "$session_id": "String",
    "$timezone": "LowCardinality(String)",
    "$window_id": "String",
}

EVENTS_PROPERTIES_JSON_SUBCOLUMNS = EVENTS_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES


PERSON_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES: dict[str, str] = {
    "$browser": "LowCardinality(String)",
    "$browser_language": "LowCardinality(String)",
    "$browser_version": "LowCardinality(String)",
    "$device_type": "LowCardinality(String)",
    "$geoip_city_name": "LowCardinality(String)",
    "$geoip_continent_code": "LowCardinality(String)",
    "$geoip_continent_name": "LowCardinality(String)",
    "$geoip_country_code": "LowCardinality(String)",
    "$geoip_country_name": "LowCardinality(String)",
    "$geoip_subdivision_1_name": "LowCardinality(String)",
    "$geoip_time_zone": "LowCardinality(String)",
    "$initial_browser": "LowCardinality(String)",
    "$initial_browser_language": "LowCardinality(String)",
    "$initial_browser_version": "LowCardinality(String)",
    "$initial_device_type": "LowCardinality(String)",
    "$initial_geoip_city_name": "LowCardinality(String)",
    "$initial_geoip_continent_code": "LowCardinality(String)",
    "$initial_geoip_continent_name": "LowCardinality(String)",
    "$initial_geoip_country_code": "LowCardinality(String)",
    "$initial_geoip_country_name": "LowCardinality(String)",
    "$initial_geoip_subdivision_1_name": "LowCardinality(String)",
    "$initial_geoip_time_zone": "LowCardinality(String)",
    "$initial_os": "LowCardinality(String)",
    "$initial_os_version": "LowCardinality(String)",
    "$os": "LowCardinality(String)",
    "$os_version": "LowCardinality(String)",
}

PERSON_PROPERTIES_JSON_SUBCOLUMNS = PERSON_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES


def EVENTS_JSON_DATA_TABLE_INDEXES() -> str:
    indexes = [
        "INDEX bloom_filter_distinct_id distinct_id TYPE bloom_filter GRANULARITY 1",
        "INDEX bloom_filter_uuid uuid TYPE bloom_filter GRANULARITY 1",
        "INDEX bloom_filter_person_id person_id TYPE bloom_filter GRANULARITY 1",
        "INDEX minmax_captured_at captured_at TYPE minmax GRANULARITY 1",
        "INDEX minmax_kafka_timestamp _timestamp TYPE minmax GRANULARITY 1",
        "INDEX minmax_inserted_at inserted_at TYPE minmax GRANULARITY 1",
        "INDEX minmax_timestamp timestamp TYPE minmax GRANULARITY 1",
        "INDEX minmax_historical_migration historical_migration TYPE minmax GRANULARITY 1",
        "INDEX minmax_created_at created_at TYPE minmax GRANULARITY 1",
    ]
    return "    , " + "\n    , ".join(indexes)


@cache
def EVENTS_JSON_INDEXED_PROPERTY_NAMES(field_name: str, index_type: str) -> frozenset[str]:
    indexed_property_names: set[str] = set()
    column_pattern = re.compile(
        rf"\b{re.escape(field_name)}\.(?:`(?P<quoted>[^`]+)`|(?P<identifier>[A-Za-z_][A-Za-z0-9_]*))"
    )

    for index_definition in EVENTS_JSON_DATA_TABLE_INDEXES().splitlines():
        type_match = re.search(r"\bTYPE\s+(?P<type>[A-Za-z_][A-Za-z0-9_]*)", index_definition)
        if type_match is None or type_match.group("type") != index_type:
            continue

        for column_match in column_pattern.finditer(index_definition):
            indexed_property_names.add(column_match.group("quoted") or column_match.group("identifier"))

    return frozenset(indexed_property_names)
