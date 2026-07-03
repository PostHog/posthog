import re

from django.conf import settings

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_EVENTS_JSON,
    CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON,
    CONSUMER_GROUP_EVENTS_JSON_WS,
    KAFKA_COLUMNS,
    STORAGE_POLICY,
    kafka_engine,
    trim_quotes_expr,
)
from posthog.clickhouse.property_groups import property_groups
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON

_CLICKHOUSE_SIMPLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BACKQUOTE_ESCAPE_CHARS_MAP = {
    "\b": "\\b",
    "\f": "\\f",
    "\r": "\\r",
    "\n": "\\n",
    "\t": "\\t",
    "\0": "\\0",
    "\a": "\\a",
    "\v": "\\v",
    "\\": "\\\\",
    "`": "\\`",
}


def _escape_clickhouse_identifier(identifier: str) -> str:
    if "%" in identifier:
        raise ValueError(f'ClickHouse identifier "{identifier}" is not permitted as it contains the "%" character')
    if _CLICKHOUSE_SIMPLE_IDENTIFIER_RE.match(identifier):
        return identifier
    return "`{}`".format("".join(_BACKQUOTE_ESCAPE_CHARS_MAP.get(char, char) for char in identifier))


def _quote_clickhouse_string_literal(value: str) -> str:
    return "'{}'".format(value.replace("\\", "\\\\").replace("'", "\\'"))


def EVENTS_DATA_TABLE():
    return "sharded_events"


def WRITABLE_EVENTS_DATA_TABLE():
    return "writable_events"


EVENTS_JSON_DATA_TABLE = "sharded_events_json"
WRITABLE_EVENTS_JSON_TABLE = "writable_events_json"
DISTRIBUTED_EVENTS_JSON_TABLE = "events_json"
KAFKA_EVENTS_NATIVE_JSON_TABLE = "kafka_events_json_native_json"


def _nullable_json_subcolumn_types(subcolumns: dict[str, str]) -> dict[str, str]:
    return {
        path: column_type if column_type.startswith("Nullable(") else f"Nullable({column_type})"
        for path, column_type in subcolumns.items()
    }


EVENTS_PROPERTIES_JSON_SUBCOLUMNS: dict[str, str] = _nullable_json_subcolumn_types(
    {
        "$active_feature_flags": "String",
        "$ai_experiment_id": "Nullable(String)",
        "$ai_http_status": "Nullable(String)",
        "$ai_is_error": "Nullable(String)",
        "$ai_model": "Nullable(String)",
        "$ai_parent_id": "Nullable(String)",
        "$ai_prompt_name": "Nullable(String)",
        "$ai_provider": "Nullable(String)",
        "$ai_session_id": "Nullable(String)",
        "$ai_span_id": "Nullable(String)",
        "$ai_total_cost_usd": "Nullable(String)",
        "$ai_trace_id": "Nullable(String)",
        "$anon_distinct_id": "Nullable(String)",
        "$app_build": "String",
        "$app_namespace": "String",
        "$app_version": "String",
        "$browser": "String",
        "$browser_version": "String",
        "$current_url": "String",
        "$device": "String",
        "$device_id": "String",
        "$device_model": "String",
        "$device_type": "String",
        "$el_text": "String",
        "$event_type": "String",
        "$exception_fingerprint": "Nullable(String)",
        "$exception_functions": "Nullable(String)",
        "$exception_issue_id": "Nullable(String)",
        "$exception_sources": "Nullable(String)",
        "$exception_types": "Nullable(String)",
        "$exception_values": "Nullable(String)",
        "$feature_flag": "String",
        "$feature_flag_payloads": "String",
        "$feature_flag_response": "String",
        "$geoip_city_name": "String",
        "$geoip_country_code": "String",
        "$geoip_country_name": "String",
        "$geoip_subdivision_1_code": "String",
        "$group_0": "String",
        "$group_1": "String",
        "$group_2": "String",
        "$group_3": "String",
        "$group_4": "String",
        "$groups": "String",
        "$host": "String",
        "$initial_pathname": "String",
        "$initial_referrer": "String",
        "$initial_referring_domain": "String",
        "$ip": "String",
        "$is_identified": "Nullable(String)",
        "$lib": "String",
        "$lib_custom_api_host": "String",
        "$lib_version": "String",
        "$lib_version__minor": "String",
        "$os": "String",
        "$os_name": "String",
        "$os_version": "String",
        "$pathname": "String",
        "$prev_pageview_max_content_percentage": "String",
        "$prev_pageview_max_scroll_percentage": "String",
        "$prev_pageview_pathname": "String",
        "$process_person_profile": "Nullable(String)",
        "$referrer": "String",
        "$referring_domain": "String",
        "$screen_height": "String",
        "$screen_name": "String",
        "$screen_width": "String",
        "$sent_at": "String",
        "$session_id": "String",
        "$survey_id": "String",
        "$survey_response": "String",
        "$survey_response_1": "String",
        "$time": "String",
        "$user_id": "String",
        "$viewport_height": "Nullable(String)",
        "$viewport_width": "Nullable(String)",
        "$web_vitals_CLS_value": "Nullable(String)",
        "$web_vitals_FCP_value": "Nullable(String)",
        "$web_vitals_INP_value": "Nullable(String)",
        "$web_vitals_LCP_value": "Nullable(String)",
        "$window_id": "String",
    }
)


def _json_present_paths(properties_expr: str, subcolumns: dict[str, str]) -> str:
    explicit_paths = ", ".join(_quote_clickhouse_string_literal(path) for path in subcolumns)
    present_typed_paths = []
    for path, column_type in subcolumns.items():
        subcolumn = f"{properties_expr}.{_escape_clickhouse_identifier(path)}"
        literal = _quote_clickhouse_string_literal(path)
        if column_type.startswith("Nullable("):
            present_typed_paths.append(f"if(isNotNull({subcolumn}), {literal}, '')")
        else:
            present_typed_paths.append(f"if(notEmpty({subcolumn}), {literal}, '')")

    return (
        "arrayConcat("
        f"arrayFilter(path -> not(has([{explicit_paths}], path)), JSONAllPaths({properties_expr})), "
        f"arrayFilter(path -> notEmpty(path), [{', '.join(present_typed_paths)}])"
        ")"
    )


def EVENTS_PROPERTIES_JSON_PRESENT_PATHS(properties_expr: str) -> str:
    return _json_present_paths(properties_expr, EVENTS_PROPERTIES_JSON_SUBCOLUMNS)


PERSON_PROPERTIES_JSON_SUBCOLUMNS: dict[str, str] = _nullable_json_subcolumn_types(
    {
        "$app_version": "String",
        "$browser": "String",
        "$current_url": "String",
        "$geoip_continent_name": "String",
        "$geoip_country_code": "String",
        "$geoip_country_name": "String",
        "$initial_current_url": "String",
        "$initial_fbclid": "String",
        "$initial_gad_source": "String",
        "$initial_gbraid": "String",
        "$initial_gclid": "String",
        "$initial_msclkid": "String",
        "$initial_pathname": "String",
        "$initial_referring_domain": "String",
        "$initial_utm_campaign": "String",
        "$initial_utm_content": "String",
        "$initial_utm_medium": "String",
        "$initial_utm_source": "String",
        "$initial_utm_term": "String",
        "$initial_wbraid": "String",
        "$os_name": "String",
        "$referring_domain": "String",
    }
)


def PERSON_PROPERTIES_JSON_PRESENT_PATHS(properties_expr: str) -> str:
    return _json_present_paths(properties_expr, PERSON_PROPERTIES_JSON_SUBCOLUMNS)


def _json_column_type(max_dynamic_types: int, max_dynamic_paths: int, subcolumns: dict[str, str]) -> str:
    explicit_paths = ", ".join(
        f"{_escape_clickhouse_identifier(name)} {column_type}" for name, column_type in subcolumns.items()
    )
    return f"JSON(max_dynamic_types = {max_dynamic_types}, max_dynamic_paths = {max_dynamic_paths}, {explicit_paths})"


def EVENTS_PROPERTIES_JSON_TYPE() -> str:
    return _json_column_type(8, 256, EVENTS_PROPERTIES_JSON_SUBCOLUMNS)


def PERSON_PROPERTIES_JSON_TYPE() -> str:
    return _json_column_type(6, 32, PERSON_PROPERTIES_JSON_SUBCOLUMNS)


def TRUNCATE_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def DROP_EVENTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


DROP_DISTRIBUTED_EVENTS_TABLE_SQL = f"DROP TABLE IF EXISTS events {ON_CLUSTER_CLAUSE()}"

INSERTED_AT_COLUMN = ", inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NOW64()"
INSERTED_AT_NOT_NULLABLE_COLUMN = ", inserted_at DateTime64(6, 'UTC') DEFAULT NOW64()"
KAFKA_CONSUMER_BREADCRUMBS_COLUMN = ", consumer_breadcrumbs Array(String)"

EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR CODEC(ZSTD(3)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties VARCHAR Codec(ZSTD(3)),
    group0_properties VARCHAR Codec(ZSTD(3)),
    group1_properties VARCHAR Codec(ZSTD(3)),
    group2_properties VARCHAR Codec(ZSTD(3)),
    group3_properties VARCHAR Codec(ZSTD(3)),
    group4_properties VARCHAR Codec(ZSTD(3)),
    group0_created_at DateTime64,
    group1_created_at DateTime64,
    group2_created_at DateTime64,
    group3_created_at DateTime64,
    group4_created_at DateTime64,
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    historical_migration Bool
    {dynamically_materialized_columns}
    {materialized_columns}
    {extra_fields}
    {indexes}
) ENGINE = {engine}
"""


# Shared per-team allocation: each team picks its slots independently from this range, and
# (team_id, slot_index) → property_name is resolved at write/read time via the dmat dictionary.
# Cap matches MAX_SLOTS_PER_TEAM so every team can fully saturate its slots.
DMAT_STRING_COLUMN_COUNT = 10


def EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS() -> str:
    s = [f"`dmat_string_{i}` Nullable(String)" for i in range(DMAT_STRING_COLUMN_COUNT)]
    return f"    , {'\n    , '.join(s)}"


def ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table: str) -> str:
    return ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(table, 0, DMAT_STRING_COLUMN_COUNT)


def ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(table: str, start: int, end_exclusive: int) -> str:
    """ALTER TABLE statement adding dmat_string columns in a half-open index range."""
    pieces = [f"ADD COLUMN IF NOT EXISTS `dmat_string_{i}` Nullable(String)" for i in range(start, end_exclusive)]
    return f"ALTER TABLE {table} \n {',\n'.join(pieces)}"


def MV_DYNAMICALLY_MATERIALIZED_COLUMNS() -> str:
    return ",\n".join(f"dmat_string_{i}" for i in range(DMAT_STRING_COLUMN_COUNT))


EVENTS_TABLE_MATERIALIZED_COLUMNS = f"""
    , $group_0 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_0')")} COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_1')")} COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_2')")} COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_3')")} COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$group_4')")} COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$window_id')")} COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR MATERIALIZED {trim_quotes_expr("JSONExtractRaw(properties, '$session_id')")} COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(JSONExtract(properties, '$session_id', 'Nullable(UUID)'))
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
    , INDEX `minmax_$group_0` `$group_0` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_1` `$group_1` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_2` `$group_2` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_3` `$group_3` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_4` `$group_4` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$window_id` `$window_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id` `$session_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id_uuid` `$session_id_uuid` TYPE minmax GRANULARITY 1
    , {", ".join(property_groups.get_create_table_pieces("sharded_events"))}
"""

EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS = f"""
    , $group_0 VARCHAR COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128)
    , elements_chain_href String COMMENT 'column_materializer::elements_chain::href'
    , elements_chain_texts Array(String) COMMENT 'column_materializer::elements_chain::texts'
    , elements_chain_ids Array(String) COMMENT 'column_materializer::elements_chain::ids'
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) COMMENT 'column_materializer::elements_chain::elements'
    , {", ".join(property_groups.get_create_table_pieces("events"))}
"""


def EVENTS_DATA_TABLE_ENGINE():
    return ReplacingMergeTree("events", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED)


def EVENTS_JSON_DATA_TABLE_ENGINE():
    return ReplacingMergeTree("events_json", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED)


def _json_subcolumn(column: str, path: str) -> str:
    return f"{_escape_clickhouse_identifier(column)}.{_escape_clickhouse_identifier(path)}"


EVENTS_JSON_DATA_COMPATIBILITY_COLUMNS = f"""
    , $group_0 String ALIAS ifNull({_json_subcolumn("properties", "$group_0")}, '')
    , $group_1 String ALIAS ifNull({_json_subcolumn("properties", "$group_1")}, '')
    , $group_2 String ALIAS ifNull({_json_subcolumn("properties", "$group_2")}, '')
    , $group_3 String ALIAS ifNull({_json_subcolumn("properties", "$group_3")}, '')
    , $group_4 String ALIAS ifNull({_json_subcolumn("properties", "$group_4")}, '')
    , $window_id String ALIAS ifNull({_json_subcolumn("properties", "$window_id")}, '')
    , $session_id String ALIAS ifNull({_json_subcolumn("properties", "$session_id")}, '')
    , $session_id_uuid Nullable(UInt128) ALIAS toUInt128(toUUIDOrNull({_json_subcolumn("properties", "$session_id")}))
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
"""


EVENTS_JSON_PROXY_COMPATIBILITY_COLUMNS = """
    , $group_0 String
    , $group_1 String
    , $group_2 String
    , $group_3 String
    , $group_4 String
    , $window_id String
    , $session_id String
    , $session_id_uuid Nullable(UInt128)
    , elements_chain_href String
    , elements_chain_texts Array(String)
    , elements_chain_ids Array(String)
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label'))
"""


EVENTS_JSON_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    uuid UUID,
    event String,
    properties {properties_json_type},
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    elements_hash String DEFAULT '',
    created_at DateTime64(6, 'UTC'),
    _timestamp DateTime,
    _offset UInt64,
    elements_chain String,
    person_id UUID,
    person_properties {person_properties_json_type},
    group0_properties String CODEC(Default),
    group1_properties String CODEC(Default),
    group2_properties String CODEC(Default),
    group3_properties String CODEC(Default),
    group4_properties String CODEC(Default),
    person_created_at DateTime64(3),
    group0_created_at DateTime64(3),
    group1_created_at DateTime64(3),
    group2_created_at DateTime64(3),
    group3_created_at DateTime64(3),
    group4_created_at DateTime64(3),
    inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT now64(),
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    is_deleted Bool DEFAULT false,
    consumer_breadcrumbs Array(String),
    historical_migration Bool DEFAULT false
    {compatibility_columns}
    {indexes}
) ENGINE = {engine}
"""


def EVENTS_JSON_DATA_TABLE_INDEXES() -> str:
    indexes = [
        "INDEX kafka_timestamp_minmax_sharded_events _timestamp TYPE minmax GRANULARITY 3",
        "INDEX `minmax_$group_0` properties.`$group_0` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$group_1` properties.`$group_1` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$group_2` properties.`$group_2` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$group_3` properties.`$group_3` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$group_4` properties.`$group_4` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$window_id` properties.`$window_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_$session_id` properties.`$session_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$sent_at` properties.`$sent_at` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$initial_pathname` properties.`$initial_pathname` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$lib_version` properties.`$lib_version` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_utm_campaign` person_properties.`$initial_utm_campaign` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_utm_medium` person_properties.`$initial_utm_medium` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_gclid` person_properties.`$initial_gclid` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_gad_source` person_properties.`$initial_gad_source` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_utm_source` person_properties.`$initial_utm_source` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_referring_domain` person_properties.`$initial_referring_domain` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_utm_term` person_properties.`$initial_utm_term` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_utm_content` person_properties.`$initial_utm_content` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_gbraid` person_properties.`$initial_gbraid` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_wbraid` person_properties.`$initial_wbraid` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_msclkid` person_properties.`$initial_msclkid` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_fbclid` person_properties.`$initial_fbclid` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$geoip_subdivision_1_code` properties.`$geoip_subdivision_1_code` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$prev_pageview_max_scroll_percentage` properties.`$prev_pageview_max_scroll_percentage` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$prev_pageview_max_content_percentage` properties.`$prev_pageview_max_content_percentage` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$prev_pageview_pathname` properties.`$prev_pageview_pathname` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_pathname` person_properties.`$initial_pathname` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$geoip_country_code` person_properties.`$geoip_country_code` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$browser_version` properties.`$browser_version` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$initial_current_url` person_properties.`$initial_current_url` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$current_url` person_properties.`$current_url` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$app_namespace` properties.`$app_namespace` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$os_name` properties.`$os_name` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$os_name` person_properties.`$os_name` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$app_version` person_properties.`$app_version` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$screen_height` properties.`$screen_height` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$screen_width` properties.`$screen_width` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$app_build` properties.`$app_build` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$geoip_country_code` properties.`$geoip_country_code` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$survey_id` properties.`$survey_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$survey_response_1` properties.`$survey_response_1` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$survey_response` properties.`$survey_response` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$el_text` properties.`$el_text` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$os_version` properties.`$os_version` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$feature_flag_payloads` properties.`$feature_flag_payloads` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$groups` properties.`$groups` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$feature_flag` properties.`$feature_flag` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$device_id` properties.`$device_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$geoip_continent_name` person_properties.`$geoip_continent_name` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$feature_flag_response` properties.`$feature_flag_response` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$referring_domain` person_properties.`$referring_domain` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$lib_version__minor` properties.`$lib_version__minor` TYPE minmax GRANULARITY 1",
        "INDEX minmax_inserted_at coalesce(inserted_at, _timestamp) TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$lib_custom_api_host` properties.`$lib_custom_api_host` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_pp_$geoip_country_name` person_properties.`$geoip_country_name` TYPE minmax GRANULARITY 1",
        "INDEX is_deleted_idx is_deleted TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$device` properties.`$device` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_issue_id` properties.`$exception_issue_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_fingerprint` properties.`$exception_fingerprint` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$web_vitals_LCP_value` properties.`$web_vitals_LCP_value` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$web_vitals_FCP_value` properties.`$web_vitals_FCP_value` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$web_vitals_CLS_value` properties.`$web_vitals_CLS_value` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$web_vitals_INP_value` properties.`$web_vitals_INP_value` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$viewport_width` properties.`$viewport_width` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$viewport_height` properties.`$viewport_height` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$anon_distinct_id` properties.`$anon_distinct_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_trace_id` properties.`$ai_trace_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_model` properties.`$ai_model` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_provider` properties.`$ai_provider` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_parent_id` properties.`$ai_parent_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_span_id` properties.`$ai_span_id` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$ai_http_status` properties.`$ai_http_status` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_types` properties.`$exception_types` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_values` properties.`$exception_values` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_sources` properties.`$exception_sources` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$exception_functions` properties.`$exception_functions` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$process_person_profile` properties.`$process_person_profile` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$app_version` properties.`$app_version` TYPE bloom_filter GRANULARITY 1",
        "INDEX `bloom_mat_$is_identified` properties.`$is_identified` TYPE bloom_filter GRANULARITY 1",
        "INDEX `minmax_$session_id_uuid` toUInt128(toUUIDOrNull(properties.`$session_id`)) TYPE minmax GRANULARITY 1",
        "INDEX `bloom_filter_$ai_trace_id` properties.`$ai_trace_id` TYPE bloom_filter(0.001) GRANULARITY 2",
        "INDEX `bloom_filter_$ai_session_id` properties.`$ai_session_id` TYPE bloom_filter GRANULARITY 1",
        "INDEX `minmax_$ai_session_id` properties.`$ai_session_id` TYPE minmax GRANULARITY 1",
        "INDEX `set_$ai_is_error` properties.`$ai_is_error` TYPE set(7) GRANULARITY 1",
        "INDEX `minmax_mat_$ai_total_cost_usd` properties.`$ai_total_cost_usd` TYPE minmax GRANULARITY 1",
        "INDEX bloom_filter_distinct_id distinct_id TYPE bloom_filter GRANULARITY 1",
        "INDEX minmax_sharded_events_timestamp timestamp TYPE minmax GRANULARITY 1",
        "INDEX minmax_historical_migration historical_migration TYPE minmax GRANULARITY 1",
        "INDEX `bloom_mat_$feature_flag` properties.`$feature_flag` TYPE bloom_filter GRANULARITY 1",
        "INDEX `bloom_filter_$ai_prompt_name` properties.`$ai_prompt_name` TYPE bloom_filter GRANULARITY 1",
        "INDEX `minmax_$ai_prompt_name` properties.`$ai_prompt_name` TYPE minmax GRANULARITY 1",
        "INDEX `bloom_filter_$ai_experiment_id` properties.`$ai_experiment_id` TYPE bloom_filter GRANULARITY 1",
        "INDEX `minmax_$ai_experiment_id` properties.`$ai_experiment_id` TYPE minmax GRANULARITY 1",
    ]
    return "    , " + "\n    , ".join(indexes)


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


def EVENTS_JSON_TABLE_SQL(on_cluster: bool = False) -> str:
    return (
        EVENTS_JSON_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMM(timestamp)
PRIMARY KEY (team_id, toDate(timestamp), event, timestamp, cityHash64(distinct_id))
ORDER BY (team_id, toDate(timestamp), event, timestamp, cityHash64(distinct_id), distinct_id, uuid)
SAMPLE BY cityHash64(distinct_id)
SETTINGS index_granularity = 8192, object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets', object_shared_data_serialization_version_for_zero_level_parts = 'map', merge_max_block_size = 131072, merge_max_block_size_bytes = 67108864, vertical_merge_algorithm_min_rows_to_activate = 0
"""
    ).format(
        table_name=EVENTS_JSON_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=EVENTS_JSON_DATA_TABLE_ENGINE(),
        properties_json_type=EVENTS_PROPERTIES_JSON_TYPE(),
        person_properties_json_type=PERSON_PROPERTIES_JSON_TYPE(),
        compatibility_columns=EVENTS_JSON_DATA_COMPATIBILITY_COLUMNS,
        indexes=EVENTS_JSON_DATA_TABLE_INDEXES(),
    )


def WRITABLE_EVENTS_JSON_TABLE_SQL(on_cluster: bool = False) -> str:
    return EVENTS_JSON_TABLE_BASE_SQL.format(
        table_name=WRITABLE_EVENTS_JSON_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(data_table=EVENTS_JSON_DATA_TABLE, sharding_key="sipHash64(distinct_id)"),
        properties_json_type=EVENTS_PROPERTIES_JSON_TYPE(),
        person_properties_json_type=PERSON_PROPERTIES_JSON_TYPE(),
        compatibility_columns="",
        indexes="",
    )


def DISTRIBUTED_EVENTS_JSON_TABLE_SQL(on_cluster: bool = False) -> str:
    return EVENTS_JSON_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_EVENTS_JSON_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(data_table=EVENTS_JSON_DATA_TABLE, sharding_key="sipHash64(distinct_id)"),
        properties_json_type=EVENTS_PROPERTIES_JSON_TYPE(),
        person_properties_json_type=PERSON_PROPERTIES_JSON_TYPE(),
        compatibility_columns=EVENTS_JSON_PROXY_COMPATIBILITY_COLUMNS,
        indexes="",
    )


def EVENTS_TABLE_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
{sample_by}
{storage_policy}
"""
    ).format(
        table_name=EVENTS_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=EVENTS_DATA_TABLE_ENGINE(),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns=EVENTS_TABLE_MATERIALIZED_COLUMNS,
        indexes=f"""
    , {index_by_kafka_timestamp(EVENTS_DATA_TABLE())}
    """,
        sample_by="SAMPLE BY cityHash64(distinct_id)",
        storage_policy=STORAGE_POLICY(),
    )


EVENTS_TABLE_INSERTED_AT_INDEX_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
ADD INDEX IF NOT EXISTS `minmax_inserted_at` COALESCE(`inserted_at`, `_timestamp`)
TYPE minmax
GRANULARITY 1
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

EVENTS_TABLE_MATERIALIZE_INSERTED_AT_INDEX_SQL = """
ALTER TABLE {table_name} ON CLUSTER {cluster}
MATERIALIZE INDEX `minmax_inserted_at`
""".format(table_name=EVENTS_DATA_TABLE(), cluster=settings.CLICKHOUSE_CLUSTER)

# we add the settings to prevent poison pills from stopping ingestion
# kafka_skip_broken_messages is an int, not a boolean, so we explicitly set
# the max block size to consume from kafka such that we skip _all_ broken messages
# this is an added safety mechanism given we control payloads to this topic


def KAFKA_EVENTS_TABLE_JSON_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100
"""
    ).format(
        table_name="kafka_events_json",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=kafka_engine(topic=KAFKA_EVENTS_JSON, group=CONSUMER_GROUP_EVENTS_JSON),
        extra_fields="",
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns="",
        indexes="",
    )


def KAFKA_EVENTS_NATIVE_JSON_TABLE_SQL(on_cluster: bool = False) -> str:
    return (
        EVENTS_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100
"""
    ).format(
        table_name=KAFKA_EVENTS_NATIVE_JSON_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_EVENTS_JSON, group=CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON),
        extra_fields="",
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns="",
        indexes="",
    )


# NOTE: All parameters must have defaults - zero-argument calls must remain valid.
# 8+ frozen migrations and schema.py reference this function without parameters.
#
# Override parameters to create separate pipelines that reuse the events schema:
# - mv_name: unique MV name to avoid conflicts with the main events_json_mv
# - kafka_table: different Kafka table consuming from a different topic
# - target_table: different target table for the MV to write to
# - on_cluster: False when running on specific node roles (e.g., ingestion layer)
#
# Example: error_tracking_events_test uses custom values to create a parallel
# pipeline for validating Node.js ingestion output against the Python pipeline.
def EVENTS_TABLE_JSON_MV_SQL(
    mv_name="events_json_mv",
    kafka_table="kafka_events_json",
    target_table=None,
    on_cluster=True,
):
    if target_table is None:
        target_table = WRITABLE_EVENTS_DATA_TABLE()

    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
historical_migration,
{dynamically_materialized_columns},
_timestamp,
_offset,
arrayMap(
    i -> _headers.value[i],
    arrayFilter(
        i -> _headers.name[i] = 'kafka-consumer-breadcrumbs',
        arrayEnumerate(_headers.name)
    )
) as consumer_breadcrumbs
FROM {database}.{kafka_table}
""".format(
        mv_name=mv_name,
        kafka_table=kafka_table,
        target_table=target_table,
        dynamically_materialized_columns=MV_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        on_cluster_clause=f"ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'" if on_cluster else "",
        database=settings.CLICKHOUSE_DATABASE,
    )


# Dual-write materialized view that writes events into the native-JSON schema
# (writable_events_json). It reads from a dedicated Kafka consumer group so JSON-table retries do not
# replay legacy writes through events_json_mv. The string properties/person_properties payloads are
# implicitly cast to the destination JSON columns on insert. Unlike the legacy MV this does not
# project the dmat_string_* columns — they don't exist on the JSON table, whose property reads come
# from JSON subcolumns instead.
def EVENTS_JSON_TABLE_MV_SQL(
    mv_name="events_json_table_mv",
    kafka_table=KAFKA_EVENTS_NATIVE_JSON_TABLE,
    target_table=None,
    on_cluster=True,
):
    if target_table is None:
        target_table = WRITABLE_EVENTS_JSON_TABLE

    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS {mv_name} {on_cluster_clause}
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
historical_migration,
_timestamp,
_offset,
arrayMap(
    i -> _headers.value[i],
    arrayFilter(
        i -> _headers.name[i] = 'kafka-consumer-breadcrumbs',
        arrayEnumerate(_headers.name)
    )
) as consumer_breadcrumbs
FROM {database}.{kafka_table}
""".format(
        mv_name=mv_name,
        kafka_table=kafka_table,
        target_table=target_table,
        on_cluster_clause=f"ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'" if on_cluster else "",
        database=settings.CLICKHOUSE_DATABASE,
    )


# WarpStream Kafka engine tables (coexist alongside MSK tables, same target)

KAFKA_EVENTS_JSON_WS_TABLE = "kafka_events_json_ws"
EVENTS_JSON_WS_MV = "events_json_ws_mv"

DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL = f"DROP TABLE IF EXISTS {KAFKA_EVENTS_JSON_WS_TABLE}"
DROP_EVENTS_JSON_WS_MV_SQL = f"DROP TABLE IF EXISTS {EVENTS_JSON_WS_MV}"


def KAFKA_EVENTS_TABLE_JSON_WS_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """
    SETTINGS kafka_skip_broken_messages = 100, kafka_thread_per_consumer = 1, kafka_num_consumers = 1
"""
    ).format(
        table_name=KAFKA_EVENTS_JSON_WS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=kafka_engine(
            topic=KAFKA_EVENTS_JSON,
            group=CONSUMER_GROUP_EVENTS_JSON_WS,
            named_collection=settings.CLICKHOUSE_KAFKA_WARPSTREAM_INGESTION_NAMED_COLLECTION,
        ),
        extra_fields="",
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns="",
        indexes="",
    )


def EVENTS_TABLE_JSON_WS_MV_SQL():
    return EVENTS_TABLE_JSON_MV_SQL(
        mv_name=EVENTS_JSON_WS_MV,
        kafka_table=KAFKA_EVENTS_JSON_WS_TABLE,
        on_cluster=False,
    )


# Events recent tables


def WRITABLE_EVENTS_RECENT_TABLE():
    return "writable_events_recent"


def EVENTS_RECENT_DATA_TABLE():
    return "events_recent"


def SHARDED_EVENTS_RECENT_DATA_TABLE():
    return "sharded_events_recent"


def DROP_KAFKA_EVENTS_RECENT_TABLE_SQL():
    return f"DROP TABLE IF EXISTS kafka_events_recent_json"


def DROP_EVENTS_RECENT_MV_TABLE_SQL():
    return f"DROP TABLE IF EXISTS events_recent_json_mv"


def TRUNCATE_EVENTS_RECENT_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {EVENTS_RECENT_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


def EVENTS_RECENT_TABLE_SQL(on_cluster=False):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name=EVENTS_RECENT_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_EVENTS_RECENT_DATA_TABLE(),
            sharding_key="sipHash64(distinct_id)",
            cluster=settings.CLICKHOUSE_PRIMARY_REPLICA_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN,
        dynamically_materialized_columns="",
        materialized_columns="",
        indexes="",
    )


def DISTRIBUTED_EVENTS_RECENT_TABLE_SQL(on_cluster=False):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="distributed_events_recent",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_EVENTS_RECENT_DATA_TABLE(),
            sharding_key="sipHash64(distinct_id)",
            cluster=settings.CLICKHOUSE_PRIMARY_REPLICA_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN,
        dynamically_materialized_columns="",
        materialized_columns="",
        indexes="",
    )


def WRITABLE_EVENTS_RECENT_TABLE_SQL(on_cluster=False):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name=WRITABLE_EVENTS_RECENT_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_EVENTS_RECENT_DATA_TABLE(),
            sharding_key="sipHash64(distinct_id)",
            cluster=settings.CLICKHOUSE_WRITABLE_CLUSTER,
        ),
        extra_fields=KAFKA_COLUMNS,
        dynamically_materialized_columns="",
        materialized_columns="",
        indexes="",
    )


def SHARDED_EVENTS_RECENT_TABLE_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """PARTITION BY toStartOfDay(inserted_at)
ORDER BY (team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))
TTL toDateTime(inserted_at) + INTERVAL 7 DAY
{storage_policy}
SETTINGS ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_EVENTS_RECENT_DATA_TABLE(),
        on_cluster_clause=ON_CLUSTER_CLAUSE(False),
        engine=ReplacingMergeTree(
            "sharded_events_recent", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED
        ),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_NOT_NULLABLE_COLUMN,
        dynamically_materialized_columns="",
        materialized_columns="",
        indexes="",
        storage_policy=STORAGE_POLICY(),
    )


def SHARDED_EVENTS_RECENT_MV_SQL():
    return """
CREATE MATERIALIZED VIEW IF NOT EXISTS events_recent_json_mv
TO {database}.{target_table}
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
person_id,
person_created_at,
person_properties,
group0_properties,
group1_properties,
group2_properties,
group3_properties,
group4_properties,
group0_created_at,
group1_created_at,
group2_created_at,
group3_created_at,
group4_created_at,
person_mode,
_timestamp,
_offset
FROM {database}.{source_table}
""".format(
        source_table=EVENTS_DATA_TABLE(),
        database=settings.CLICKHOUSE_DATABASE,
        target_table=WRITABLE_EVENTS_RECENT_TABLE(),
    )


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED


# This table is responsible for writing to sharded_events based on a sharding key.
def WRITABLE_EVENTS_TABLE_SQL():
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="writable_events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(),
        engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
        extra_fields=KAFKA_COLUMNS + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns="",
        indexes="",
    )


# This table is responsible for reading from events on a cluster setting


def DISTRIBUTED_EVENTS_TABLE_SQL(on_cluster=True):
    return EVENTS_TABLE_BASE_SQL.format(
        table_name="events",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(data_table=EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
        extra_fields=KAFKA_COLUMNS + INSERTED_AT_COLUMN + KAFKA_CONSUMER_BREADCRUMBS_COLUMN,
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns=EVENTS_TABLE_PROXY_MATERIALIZED_COLUMNS,
        indexes="",
    )


def INSERT_EVENT_SQL(table_name: str | None = None) -> str:
    if table_name is None:
        table_name = EVENTS_DATA_TABLE()

    return f"""
INSERT INTO {table_name}
(
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    person_id,
    person_properties,
    person_created_at,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    created_at,
    _timestamp,
    _offset
)
VALUES
(
    %(uuid)s,
    %(event)s,
    %(properties)s,
    %(timestamp)s,
    %(team_id)s,
    %(distinct_id)s,
    %(elements_chain)s,
    %(person_id)s,
    %(person_properties)s,
    %(person_created_at)s,
    %(group0_properties)s,
    %(group1_properties)s,
    %(group2_properties)s,
    %(group3_properties)s,
    %(group4_properties)s,
    %(group0_created_at)s,
    %(group1_created_at)s,
    %(group2_created_at)s,
    %(group3_created_at)s,
    %(group4_created_at)s,
    %(person_mode)s,
    %(created_at)s,
    now(),
    0
)
"""


def BULK_INSERT_EVENT_SQL(table_name: str | None = None) -> str:
    if table_name is None:
        table_name = EVENTS_DATA_TABLE()

    return f"""
INSERT INTO {table_name}
(
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    person_id,
    person_properties,
    person_created_at,
    group0_properties,
    group1_properties,
    group2_properties,
    group3_properties,
    group4_properties,
    group0_created_at,
    group1_created_at,
    group2_created_at,
    group3_created_at,
    group4_created_at,
    person_mode,
    created_at,
    _timestamp,
    _offset
)
VALUES
"""


NULL_SQL = """
-- Creates zero values for all date axis ticks for the given date_from, date_to range
SELECT toUInt16(0) AS total, {date_to_truncated} - {interval_func}(number) AS day_start

-- Get the number of `intervals` between date_from and date_to.
--
-- NOTE: for week there is some unusual behavior, see:
--       https://github.com/ClickHouse/ClickHouse/issues/7322
--
--       This actually aligns with what we want, as they are assuming Sunday week starts,
--       and we'd rather have the relative week num difference. Likewise the same for
--       "month" intervals
--
--       To ensure we get all relevant intervals, we add in the truncated "date_from"
--       value.
--
--       This behaviour of dateDiff is different to our handling of "week" and "month"
--       differences we are performing in python, which just considers seconds between
--       date_from and date_to
--
-- TODO: Ths pattern of generating intervals is repeated in several places. Reuse this
--       `ticks` query elsewhere.
FROM numbers(dateDiff(%(interval)s, {date_from_truncated}, toDateTime(%(date_to)s, %(timezone)s)))

UNION ALL

-- Make sure we capture the interval date_from falls into.
SELECT toUInt16(0) AS total, {date_from_truncated}
"""

EVENT_JOIN_PERSON_SQL = """
INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi ON events.distinct_id = pdi.distinct_id
"""

GET_EVENTS_WITH_PROPERTIES = """
SELECT * FROM events WHERE
team_id = %(team_id)s
{filters}
{order_by}
"""

EXTRACT_TAG_REGEX = "extract(elements_chain, '^(.*?)[.|:]')"
EXTRACT_TEXT_REGEX = "extract(elements_chain, 'text=\"(.*?)\"')"

ELEMENT_TAG_COUNT = """
SELECT concat('<', {tag_regex}, '> ', {text_regex}) AS tag_name,
       events.elements_chain,
       count(*) as tag_count
FROM events
WHERE events.team_id = %(team_id)s AND event = '$autocapture'
GROUP BY tag_name, elements_chain
ORDER BY tag_count desc, tag_name
LIMIT %(limit)s
""".format(tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX)

GET_CUSTOM_EVENTS = """
SELECT DISTINCT event FROM events where team_id = %(team_id)s AND event NOT IN ['$autocapture', '$pageview', '$identify', '$pageleave', '$screen']
"""

#
# Demo data
#

COPY_EVENTS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=WRITABLE_EVENTS_DATA_TABLE(),
    columns_except_team_id="""uuid, event, properties, timestamp, distinct_id, elements_chain, created_at, person_id, person_created_at,
    person_properties, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
     group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at, person_mode""",
)
