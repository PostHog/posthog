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


def _json_subcolumn_type_supports_nullable(column_type: str) -> bool:
    return not column_type.startswith(("Array(", "Map("))


def _nullable_json_subcolumn_types(subcolumns: dict[str, str]) -> dict[str, str]:
    return {
        path: column_type
        if column_type.startswith("Nullable(") or not _json_subcolumn_type_supports_nullable(column_type)
        else f"Nullable({column_type})"
        for path, column_type in subcolumns.items()
    }


# Scalar JSON subcolumns are wrapped as Nullable so missing/JSON-null values stay distinct from scalar defaults such as
# an empty string. Arrays and maps stay non-nullable because ClickHouse does not support Nullable(Array(...)) or
# Nullable(Map(...)).
EVENTS_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES: dict[str, str] = {
    "$active_feature_flags": "Array(String)",
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
    "$exception_functions": "Array(String)",
    "$exception_issue_id": "Nullable(String)",
    "$exception_sources": "Array(String)",
    "$exception_types": "Array(String)",
    "$exception_values": "Array(String)",
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

EVENTS_PROPERTIES_JSON_SUBCOLUMNS: dict[str, str] = _nullable_json_subcolumn_types(
    EVENTS_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES
)


PERSON_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES: dict[str, str] = {
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

PERSON_PROPERTIES_JSON_SUBCOLUMNS: dict[str, str] = _nullable_json_subcolumn_types(
    PERSON_PROPERTIES_JSON_SUBCOLUMN_DECLARED_TYPES
)


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
        "INDEX bf_active_feature_flags properties.`$active_feature_flags` TYPE bloom_filter(0.01) GRANULARITY 1",
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
        "INDEX `minmax_mat_$process_person_profile` properties.`$process_person_profile` TYPE minmax GRANULARITY 1",
        "INDEX `minmax_mat_$app_version` properties.`$app_version` TYPE minmax GRANULARITY 1",
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
