from django.conf import settings

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_EVENTS_JSON,
    CONSUMER_GROUP_EVENTS_JSON_WS,
    KAFKA_COLUMNS,
    STORAGE_POLICY,
    kafka_engine,
)
from posthog.clickhouse.property_groups import property_groups
from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON


def _print_json_path(path: str) -> str:
    if path.replace("_", "a").isalnum() and not path[0].isdigit():
        return path
    return f"`{path.replace('`', '``')}`"


def _json_column_type(max_dynamic_types: int, max_dynamic_paths: int, typed_paths: tuple[tuple[str, str], ...]) -> str:
    path_definitions = ", ".join(f"{_print_json_path(path)} {type_name}" for path, type_name in typed_paths)
    return f"JSON(max_dynamic_types = {max_dynamic_types}, max_dynamic_paths = {max_dynamic_paths}, {path_definitions})"


def _events_table_settings(*settings_sql: str) -> str:
    settings_items = [
        "index_granularity = 8192",
        "object_serialization_version = 'v3'",
        "object_shared_data_serialization_version = 'map_with_buckets'",
        "object_shared_data_serialization_version_for_zero_level_parts = 'map'",
        "merge_max_block_size = 131072",
        "merge_max_block_size_bytes = 67108864",
        "vertical_merge_algorithm_min_rows_to_activate = 0",
    ]
    for setting_sql in settings_sql:
        setting_sql = setting_sql.strip()
        if not setting_sql:
            continue
        if setting_sql.startswith("SETTINGS "):
            setting_sql = setting_sql.removeprefix("SETTINGS ").strip()
        settings_items.append(setting_sql)
    return f"SETTINGS {', '.join(settings_items)}"


EVENTS_PROPERTIES_JSON_TYPED_PATHS: tuple[tuple[str, str], ...] = (
    ("$active_feature_flags", "String"),
    ("$ai_experiment_id", "Nullable(String)"),
    ("$ai_http_status", "Nullable(String)"),
    ("$ai_is_error", "Nullable(String)"),
    ("$ai_model", "Nullable(String)"),
    ("$ai_parent_id", "Nullable(String)"),
    ("$ai_prompt_name", "Nullable(String)"),
    ("$ai_provider", "Nullable(String)"),
    ("$ai_session_id", "Nullable(String)"),
    ("$ai_span_id", "Nullable(String)"),
    ("$ai_total_cost_usd", "Nullable(String)"),
    ("$ai_trace_id", "Nullable(String)"),
    ("$anon_distinct_id", "Nullable(String)"),
    ("$app_build", "String"),
    ("$app_namespace", "String"),
    ("$app_version", "String"),
    ("$browser", "String"),
    ("$browser_version", "String"),
    ("$current_url", "String"),
    ("$device", "String"),
    ("$device_id", "String"),
    ("$device_model", "String"),
    ("$device_type", "String"),
    ("$el_text", "String"),
    ("$event_type", "String"),
    ("$exception_fingerprint", "Nullable(String)"),
    ("$exception_functions", "Nullable(String)"),
    ("$exception_issue_id", "Nullable(String)"),
    ("$exception_sources", "Nullable(String)"),
    ("$exception_types", "Nullable(String)"),
    ("$exception_values", "Nullable(String)"),
    ("$feature_flag", "String"),
    ("$feature_flag_payloads", "String"),
    ("$feature_flag_response", "String"),
    ("$geoip_city_name", "String"),
    ("$geoip_country_code", "String"),
    ("$geoip_country_name", "String"),
    ("$geoip_subdivision_1_code", "String"),
    ("$group_0", "String"),
    ("$group_1", "String"),
    ("$group_2", "String"),
    ("$group_3", "String"),
    ("$group_4", "String"),
    ("$groups", "String"),
    ("$host", "String"),
    ("$initial_pathname", "String"),
    ("$initial_referrer", "String"),
    ("$initial_referring_domain", "String"),
    ("$ip", "String"),
    ("$is_identified", "Nullable(String)"),
    ("$lib", "String"),
    ("$lib_custom_api_host", "String"),
    ("$lib_version", "String"),
    ("$lib_version__minor", "String"),
    ("$os", "String"),
    ("$os_name", "String"),
    ("$os_version", "String"),
    ("$pathname", "String"),
    ("$prev_pageview_max_content_percentage", "String"),
    ("$prev_pageview_max_scroll_percentage", "String"),
    ("$prev_pageview_pathname", "String"),
    ("$process_person_profile", "Nullable(String)"),
    ("$referrer", "String"),
    ("$referring_domain", "String"),
    ("$screen_height", "String"),
    ("$screen_name", "String"),
    ("$screen_width", "String"),
    ("$sent_at", "String"),
    ("$session_id", "String"),
    ("$survey_id", "String"),
    ("$survey_response", "String"),
    ("$survey_response_1", "String"),
    ("$time", "String"),
    ("$user_id", "String"),
    ("$viewport_height", "Nullable(String)"),
    ("$viewport_width", "Nullable(String)"),
    ("$web_vitals_CLS_value", "Nullable(String)"),
    ("$web_vitals_FCP_value", "Nullable(String)"),
    ("$web_vitals_INP_value", "Nullable(String)"),
    ("$web_vitals_LCP_value", "Nullable(String)"),
    ("$window_id", "String"),
    ("Account.client_id", "String"),
    ("Connection.app.name", "String"),
    ("Event.productCode", "String"),
    ("HTTP Method", "String"),
    ("Plan type and filter", "String"),
    ("Subscription.plan.amount", "String"),
    ("action", "String"),
    ("action_name", "String"),
    ("address", "String"),
    ("apiErrorMessage", "String"),
    ("apiName", "String"),
    ("app_name", "String"),
    ("app_version", "String"),
    ("arguments", "String"),
    ("audio_duration", "String"),
    ("authentication_method", "String"),
    ("auto_chapters", "String"),
    ("auto_highlights", "String"),
    ("category", "String"),
    ("chain", "String"),
    ("channel", "String"),
    ("client_id", "String"),
    ("client_name", "String"),
    ("commit_sha", "String"),
    ("community_id", "String"),
    ("conceptName", "String"),
    ("content_length", "String"),
    ("content_safety", "String"),
    ("context", "String"),
    ("contributionError", "String"),
    ("created_at", "String"),
    ("created_by", "String"),
    ("created_by_system", "String"),
    ("currentScreen", "String"),
    ("current_member_guid", "String"),
    ("customer_email", "String"),
    ("deal_id", "String"),
    ("device_type", "String"),
    ("disable_institution_search", "String"),
    ("disfluencies", "String"),
    ("distinct_id", "String"),
    ("dual_channel", "String"),
    ("duration", "String"),
    ("email", "String"),
    ("email_domain", "String"),
    ("entity_detection", "String"),
    ("env", "String"),
    ("environment", "String"),
    ("event", "String"),
    ("event_count_in_month", "String"),
    ("event_count_in_period", "String"),
    ("events_projected_amount", "String"),
    ("fbclid", "String"),
    ("filter_profanity", "String"),
    ("filters_count", "String"),
    ("function", "String"),
    ("gad_source", "String"),
    ("gbraid", "String"),
    ("gclid", "String"),
    ("gross", "String"),
    ("group_id", "String"),
    ("historical_migration", "Nullable(String)"),
    ("iab_categories", "String"),
    ("id", "String"),
    ("index", "String"),
    ("initial_dclid", "String"),
    ("initial_fbclid", "String"),
    ("initial_gclsrc", "String"),
    ("initial_igshid", "String"),
    ("initial_li_fat_id", "String"),
    ("initial_mc_cid", "String"),
    ("initial_msclkid", "String"),
    ("initial_step", "String"),
    ("initial_ttclid", "String"),
    ("initial_twclid", "String"),
    ("initial_wbraid", "String"),
    ("initiator", "String"),
    ("insight", "String"),
    ("institution_name", "String"),
    ("inviteCode", "String"),
    ("is_demo_project", "String"),
    ("is_first_component_load", "String"),
    ("is_first_event_for_user", "String"),
    ("is_initial_aggregation", "String"),
    ("is_oauth", "String"),
    ("is_organization_first_user", "String"),
    ("is_test_user", "String"),
    ("item_count", "String"),
    ("job_type", "String"),
    ("key", "String"),
    ("kind", "String"),
    ("language_detection", "String"),
    ("machine_id", "String"),
    ("message", "String"),
    ("method", "String"),
    ("mode", "String"),
    ("most_recent_app_os", "String"),
    ("msclkid", "String"),
    ("name", "String"),
    ("nativeBuildVersion", "String"),
    ("numberOfSecrets", "String"),
    ("orderId", "String"),
    ("orderType", "String"),
    ("organization", "String"),
    ("organization_id", "String"),
    ("organization_name", "String"),
    ("organizations", "String"),
    ("origin", "String"),
    ("osName", "String"),
    ("owner_type", "String"),
    ("page", "String"),
    ("payment_status", "String"),
    ("phone", "String"),
    ("platform", "String"),
    ("product", "String"),
    ("product_analytics_projected_amount", "String"),
    ("product_key", "String"),
    ("progress", "String"),
    ("protocol", "String"),
    ("query", "String"),
    ("ramp", "String"),
    ("realm", "String"),
    ("record-id", "String"),
    ("recording_count_in_period", "String"),
    ("recordings_projected_amount", "String"),
    ("redact_pii", "String"),
    ("referrer", "String"),
    ("referrer_id", "String"),
    ("region", "String"),
    ("revenue", "String"),
    ("screen_name", "String"),
    ("sdk", "String"),
    ("search_term", "String"),
    ("sentiment_analysis", "String"),
    ("session_replay_projected_amount", "String"),
    ("sku", "String"),
    ("source", "String"),
    ("speaker_labels", "String"),
    ("statusCode", "String"),
    ("status_message", "String"),
    ("store_url", "String"),
    ("stripe_amount_paid", "String"),
    ("subdomain", "String"),
    ("subscriptionStatus", "String"),
    ("summarization", "String"),
    ("surface_tag", "String"),
    ("survey_responses_count_in_period", "String"),
    ("symbol", "String"),
    ("tag", "String"),
    ("target", "String"),
    ("team", "String"),
    ("testSessionId", "String"),
    ("thread_id", "String"),
    ("ticketId", "String"),
    ("title", "String"),
    ("token", "String"),
    ("total_event_actions_count", "String"),
    ("total_usd", "String"),
    ("type", "String"),
    ("url", "String"),
    ("url_promotion_id", "String"),
    ("usd", "String"),
    ("user_agent", "String"),
    ("user_email_domain", "String"),
    ("user_platform", "String"),
    ("utm_campaign", "String"),
    ("utm_content", "String"),
    ("utm_medium", "String"),
    ("utm_source", "String"),
    ("valid_ach_accounts", "String"),
    ("wbraid", "String"),
    ("wlo_enabled", "String"),
    ("workplace_billing_plan", "String"),
    ("workspace", "String"),
    ("workspaceId", "String"),
)


EVENTS_PERSON_PROPERTIES_JSON_TYPED_PATHS: tuple[tuple[str, str], ...] = (
    ("$app_version", "String"),
    ("$browser", "String"),
    ("$current_url", "String"),
    ("$geoip_continent_name", "String"),
    ("$geoip_country_code", "String"),
    ("$geoip_country_name", "String"),
    ("$initial_current_url", "String"),
    ("$initial_fbclid", "String"),
    ("$initial_gad_source", "String"),
    ("$initial_gbraid", "String"),
    ("$initial_gclid", "String"),
    ("$initial_msclkid", "String"),
    ("$initial_pathname", "String"),
    ("$initial_referring_domain", "String"),
    ("$initial_utm_campaign", "String"),
    ("$initial_utm_content", "String"),
    ("$initial_utm_medium", "String"),
    ("$initial_utm_source", "String"),
    ("$initial_utm_term", "String"),
    ("$initial_wbraid", "String"),
    ("$os_name", "String"),
    ("$referring_domain", "String"),
    ("Email Domain", "String"),
    ("companyName", "String"),
    ("customer", "String"),
    ("email", "String"),
    ("hubspot_score", "String"),
    ("id", "String"),
    ("role", "String"),
    ("serverMarketing", "String"),
    ("serverMasterclass", "String"),
    ("user_email_domain", "String"),
    ("username", "String"),
    ("utm_source", "String"),
    ("val_region", "String"),
)

EVENTS_PROPERTIES_COLUMN_TYPE = _json_column_type(8, 256, EVENTS_PROPERTIES_JSON_TYPED_PATHS)
EVENTS_PERSON_PROPERTIES_COLUMN_TYPE = _json_column_type(6, 32, EVENTS_PERSON_PROPERTIES_JSON_TYPED_PATHS)
EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS = {
    "properties_column_type": EVENTS_PROPERTIES_COLUMN_TYPE,
    "person_properties_column_type": EVENTS_PERSON_PROPERTIES_COLUMN_TYPE,
}
EVENTS_JSON_PROPERTY_GROUP_SOURCE_EXPRESSIONS = {
    "properties": "toJSONString(properties)",
    "person_properties": "toJSONString(person_properties)",
}


def EVENTS_DATA_TABLE():
    return "sharded_events"


def WRITABLE_EVENTS_DATA_TABLE():
    return "writable_events"


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
    properties {properties_column_type},
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC'),
    person_id UUID,
    person_created_at DateTime64,
    person_properties {person_properties_column_type},
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


def EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS() -> str:
    s = []

    # Add string columns (0-9)
    for i in range(10):
        s.append(f"`dmat_string_{i}` Nullable(String)")

    # Add numeric columns (0-9)
    for i in range(10):
        s.append(f"`dmat_numeric_{i}` Nullable(Float64)")

    # Add bool columns (0-9)
    for i in range(10):
        s.append(f"`dmat_bool_{i}` Nullable(UInt8)")

    # Add datetime columns (0-9)
    for i in range(10):
        s.append(f"`dmat_datetime_{i}` Nullable(DateTime64(6, 'UTC'))")

    return f"    , {'\n    , '.join(s)}"


def ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table: str) -> str:
    s = []

    # Add string columns (0-9)
    for i in range(10):
        s.append(f"ADD COLUMN IF NOT EXISTS `dmat_string_{i}` Nullable(String)")

    # Add numeric columns (0-9)
    for i in range(10):
        s.append(f"ADD COLUMN IF NOT EXISTS `dmat_numeric_{i}` Nullable(Float64)")

    # Add bool columns (0-9)
    for i in range(10):
        s.append(f"ADD COLUMN IF NOT EXISTS `dmat_bool_{i}` Nullable(UInt8)")

    # Add datetime columns (0-9)
    for i in range(10):
        s.append(f"ADD COLUMN IF NOT EXISTS `dmat_datetime_{i}` Nullable(DateTime64(6, 'UTC'))")

    separator = ",\n"
    return f"ALTER TABLE {table} \n {separator.join(s)}"


def MV_DYNAMICALLY_MATERIALIZED_COLUMNS() -> str:
    s = []
    for i in range(10):
        s.append(f"dmat_string_{i}")
    for i in range(10):
        s.append(f"dmat_numeric_{i}")
    for i in range(10):
        s.append(f"dmat_bool_{i}")
    for i in range(10):
        s.append(f"dmat_datetime_{i}")
    return ",\n".join(s)


EVENTS_TABLE_MATERIALIZED_COLUMNS = f"""
    , $group_0 VARCHAR MATERIALIZED properties.`$group_0` COMMENT 'column_materializer::$group_0'
    , $group_1 VARCHAR MATERIALIZED properties.`$group_1` COMMENT 'column_materializer::$group_1'
    , $group_2 VARCHAR MATERIALIZED properties.`$group_2` COMMENT 'column_materializer::$group_2'
    , $group_3 VARCHAR MATERIALIZED properties.`$group_3` COMMENT 'column_materializer::$group_3'
    , $group_4 VARCHAR MATERIALIZED properties.`$group_4` COMMENT 'column_materializer::$group_4'
    , $window_id VARCHAR MATERIALIZED properties.`$window_id` COMMENT 'column_materializer::$window_id'
    , $session_id VARCHAR MATERIALIZED properties.`$session_id` COMMENT 'column_materializer::$session_id'
    , $session_id_uuid Nullable(UInt128) MATERIALIZED toUInt128(toUUIDOrNull(properties.`$session_id`))
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
    , INDEX `minmax_$group_0` properties.`$group_0` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_1` properties.`$group_1` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_2` properties.`$group_2` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_3` properties.`$group_3` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$group_4` properties.`$group_4` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$window_id` properties.`$window_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id` properties.`$session_id` TYPE minmax GRANULARITY 1
    , INDEX `minmax_$session_id_uuid` toUInt128(toUUIDOrNull(properties.`$session_id`)) TYPE minmax GRANULARITY 1
    , {", ".join(property_groups.get_create_table_pieces("sharded_events", EVENTS_JSON_PROPERTY_GROUP_SOURCE_EXPRESSIONS))}
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
        storage_policy=_events_table_settings(STORAGE_POLICY()),
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
    )


def SHARDED_EVENTS_RECENT_TABLE_SQL():
    return (
        EVENTS_TABLE_BASE_SQL
        + """PARTITION BY toStartOfDay(inserted_at)
ORDER BY (team_id, toStartOfHour(inserted_at), event, cityHash64(distinct_id), cityHash64(uuid))
TTL toDateTime(inserted_at) + INTERVAL 7 DAY
{storage_policy}
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
        storage_policy=_events_table_settings(STORAGE_POLICY(), "ttl_only_drop_parts = 1"),
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
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
        **EVENTS_TABLE_JSON_COLUMN_FORMAT_ARGS,
    )


INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()}
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
)

BULK_INSERT_EVENT_SQL = (
    lambda: f"""
INSERT INTO {EVENTS_DATA_TABLE()}
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
)


SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT
    DISTINCT {property_field}
FROM
    events
WHERE
    team_id = %(team_id)s
    {property_exists_filter}
    {parsed_date_from}
    {parsed_date_to}
    {event_filter}
    {value_filter}
{order_by_clause}
LIMIT 10
"""

SELECT_EVENT_BY_TEAM_AND_CONDITIONS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM
    events
where team_id = %(team_id)s
{conditions}
ORDER BY timestamp {order} {limit}
"""

SELECT_EVENT_BY_TEAM_AND_CONDITIONS_FILTERS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events
WHERE
team_id = %(team_id)s
{conditions}
{filters}
ORDER BY timestamp {order} {limit}
"""

SELECT_ONE_EVENT_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE uuid = %(event_id)s AND team_id = %(team_id)s
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
