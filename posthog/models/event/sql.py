from posthog.hogql.escape_sql import escape_clickhouse_identifier, escape_clickhouse_string
from posthog.hogql.functions.udfs import JSON_STRIP_EMPTY_STRINGS_AND_NULLS_CLICKHOUSE_NAME

from posthog.clickhouse.base_sql import COPY_ROWS_BETWEEN_TEAMS_BASE_SQL
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE

# The events-JSON schema declarations (table names, JSON subcolumn types, index DDL) live in the
# Django-free posthog.clickhouse.events_json module so the HogQL engine can use them without
# booting Django; re-exported here for existing callers.
from posthog.clickhouse.events_json import (
    DISTRIBUTED_EVENTS_JSON_TABLE as DISTRIBUTED_EVENTS_JSON_TABLE,
    EVENTS_JSON_DATA_TABLE,
    EVENTS_JSON_DATA_TABLE_INDEXES,
    EVENTS_JSON_INDEXED_PROPERTY_NAMES,  # noqa: F401
    EVENTS_JSON_INSERT_SETTINGS,
    EVENTS_PROPERTIES_JSON_MAX_DYNAMIC_PATHS,
    EVENTS_PROPERTIES_JSON_SUBCOLUMNS,
    KAFKA_EVENTS_NATIVE_JSON_TABLE,
    PERSON_PROPERTIES_JSON_MAX_DYNAMIC_PATHS,
    PERSON_PROPERTIES_JSON_SUBCOLUMNS,
    TEMPORARY_PROPERTIES_JSON_TYPE,
    WRITABLE_EVENTS_JSON_TABLE as WRITABLE_EVENTS_JSON_TABLE,
)
from posthog.clickhouse.kafka_engine import (
    CONSUMER_GROUP_EVENTS_JSON,
    CONSUMER_GROUP_EVENTS_JSON_NATIVE_JSON,
    kafka_engine,
)
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON


def EVENTS_DATA_TABLE():
    return "sharded_events"


def WRITABLE_EVENTS_DATA_TABLE():
    return "writable_events"


def _json_column_type(subcolumns: dict[str, str], max_dynamic_paths: int) -> str:
    explicit_paths = ", ".join(
        f"{escape_clickhouse_identifier(name)} {column_type}" for name, column_type in subcolumns.items()
    )
    return f"JSON(max_dynamic_paths = {max_dynamic_paths}, {explicit_paths})"


def EVENTS_PROPERTIES_JSON_TYPE() -> str:
    return _json_column_type(EVENTS_PROPERTIES_JSON_SUBCOLUMNS, EVENTS_PROPERTIES_JSON_MAX_DYNAMIC_PATHS)


def PERSON_PROPERTIES_JSON_TYPE() -> str:
    return _json_column_type(PERSON_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_MAX_DYNAMIC_PATHS)


def json_property_presence_expr(column: str, prop: str) -> str:
    """SQL predicate testing whether a (possibly dotted) property path is present in a native-JSON
    events column, for deletion/mutation predicates that run against the JSON events tables.

    Mirrors the HogQL resolver's JSONHas lowering, with the materialized-column rule that an empty
    value is absent: a declared path is present when it is not null and not empty; a dynamic path
    is present when its scalar read is a non-empty string or its sub-object holds a non-empty value.
    ClickHouse's JSONHas() cannot be used directly on a JSON-typed column — it does not see typed
    paths or nested objects there.
    """
    if column not in ("properties", "person_properties", "temporary_properties"):
        raise ValueError(f"unsupported JSON events column: {column}")
    subcolumns = {
        "properties": EVENTS_PROPERTIES_JSON_SUBCOLUMNS,
        "person_properties": PERSON_PROPERTIES_JSON_SUBCOLUMNS,
        "temporary_properties": {},
    }[column]
    if column == "properties" and prop.startswith("$feature/"):
        key = escape_clickhouse_string(prop.removeprefix("$feature/"))
        return f"mapContains(properties.`$feature_flags`, {key})"
    parts = prop.split(".")
    column_sql = escape_clickhouse_identifier(column)
    path_sql = ".".join(escape_clickhouse_identifier(part) for part in parts)
    scalar = f"{column_sql}.{path_sql}"
    # Declared paths can be dotted ($groups.organization), so match the whole path before the head.
    if prop in subcolumns:
        if not subcolumns[prop].startswith("Nullable("):
            return f"notEmpty({scalar})"
        return f"isNotNull({scalar})"
    if len(parts) > 1 and parts[0] in subcolumns:
        head = f"{column_sql}.{escape_clickhouse_identifier(parts[0])}"
        head_document = head if subcolumns[parts[0]] in ("String", "Nullable(String)") else f"toJSONString({head})"
        tail = ", ".join(escape_clickhouse_string(part) for part in parts[1:])
        return f"JSONHas(ifNull({head_document}, ''), {tail})"
    # The sub-object serializes the '' default of every declared path under it, so strip empty
    # values before the emptiness check.
    sub_object = f"{column_sql}.^{path_sql}"
    return (
        f"(notEmpty(ifNull(toString({scalar}), '')) "
        f"OR {JSON_STRIP_EMPTY_STRINGS_AND_NULLS_CLICKHOUSE_NAME}(toJSONString({sub_object})) != '{{}}')"
    )


def TRUNCATE_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()}"


# Shared per-team allocation: each team picks its slots independently from this range, and
# (team_id, slot_index) → property_name is resolved at write/read time via the dmat dictionary.
# Cap matches MAX_SLOTS_PER_TEAM so every team can fully saturate its slots.
DMAT_STRING_COLUMN_COUNT = 10


# The subquery alias is computed once per row, so reading six tuple fields costs one process round trip.
EVENTS_JSON_CLEANER = "JSONCleanPostHogEvent"
EVENTS_JSON_CLEANED_ALIAS = "cleaned"


def SHARDED_EVENTS_RECENT_DATA_TABLE():
    return "sharded_events_recent"


def EVENTS_RECENT_DATA_TABLE() -> str:
    return "events_recent"


def BULK_INSERT_EVENT_SQL(table_name: str | None = None, *, values: str = "") -> str:
    if table_name is None:
        table_name = EVENTS_DATA_TABLE()

    # Native fixtures need ingestion cleanup, and VALUES cannot execute an external UDF. c3 is properties and c9
    # is person_properties in the positional column list below.
    source = (
        f"SELECT * EXCEPT ({EVENTS_JSON_CLEANED_ALIAS}) "
        f"REPLACE ({EVENTS_JSON_CLEANED_ALIAS}.properties AS c3, {EVENTS_JSON_CLEANED_ALIAS}.person_properties AS c9), "
        f"{EVENTS_JSON_CLEANED_ALIAS}.temporary_properties, {EVENTS_JSON_CLEANED_ALIAS}.properties_null_keys, "
        f"{EVENTS_JSON_CLEANED_ALIAS}.temporary_properties_null_keys, {EVENTS_JSON_CLEANED_ALIAS}.person_properties_null_keys "
        f"FROM (SELECT *, {EVENTS_JSON_CLEANER}(c3, c9) AS {EVENTS_JSON_CLEANED_ALIAS} FROM values({values})) AS source "
        f"SETTINGS {EVENTS_JSON_INSERT_SETTINGS}"
        if table_name == EVENTS_JSON_DATA_TABLE
        else f"VALUES{values}"
    )
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
    _offset{", temporary_properties, properties_null_keys, temporary_properties_null_keys, person_properties_null_keys" if table_name == EVENTS_JSON_DATA_TABLE else ""}
)
{source}
"""


def INSERT_EVENT_SQL(table_name: str | None = None) -> str:
    return BULK_INSERT_EVENT_SQL(
        table_name,
        values="""
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
)""",
    )


#
# Demo data
#

COPY_EVENTS_BETWEEN_TEAMS = COPY_ROWS_BETWEEN_TEAMS_BASE_SQL.format(
    table_name=WRITABLE_EVENTS_DATA_TABLE(),
    columns_except_team_id="""uuid, event, properties, timestamp, distinct_id, elements_chain, created_at, person_id, person_created_at,
    person_properties, group0_properties, group1_properties, group2_properties, group3_properties, group4_properties,
     group0_created_at, group1_created_at, group2_created_at, group3_created_at, group4_created_at, person_mode""",
)

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


def EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS() -> str:
    s = [f"`dmat_string_{i}` Nullable(String)" for i in range(DMAT_STRING_COLUMN_COUNT)]
    return f"    , {'\n    , '.join(s)}"


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
        extra_fields=", captured_at Nullable(DateTime64(6, 'UTC'))",
        dynamically_materialized_columns=EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS(),
        materialized_columns="",
        indexes="",
    )


def TRUNCATE_EVENTS_JSON_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {EVENTS_JSON_DATA_TABLE} {ON_CLUSTER_CLAUSE()}"


def EVENTS_JSON_DATA_TABLE_ENGINE():
    return ReplacingMergeTree("events_json", ver="_timestamp", replication_scheme=ReplicationScheme.SHARDED)


EVENTS_JSON_ELEMENTS_COLUMNS = """
    , elements_chain_href String MATERIALIZED extract(elements_chain, '(?::|\")href="(.*?)"')
    , elements_chain_texts Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")text="(.*?)"'))
    , elements_chain_ids Array(String) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id="(.*?)"'))
    , elements_chain_elements Array(Enum('a', 'button', 'form', 'input', 'select', 'textarea', 'label')) MATERIALIZED arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))
"""

EVENTS_JSON_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    uuid UUID,
    event String,
    properties {properties_json_type},
    temporary_properties {temporary_properties_json_type}{temporary_properties_storage},
    properties_null_keys Array(LowCardinality(String)),
    temporary_properties_null_keys Array(LowCardinality(String)){temporary_properties_storage},
    timestamp DateTime64(6, 'UTC'){gcd_codec},
    team_id Int64,
    distinct_id String,
    created_at DateTime64(6, 'UTC') DEFAULT now(){gcd_codec},
    _timestamp DateTime{t64_codec},
    _offset UInt64{t64_codec},
    elements_chain String,
    person_id UUID,
    person_properties {person_properties_json_type},
    person_properties_null_keys Array(LowCardinality(String)),
    group0_properties String,
    group1_properties String,
    group2_properties String,
    group3_properties String,
    group4_properties String,
    person_created_at DateTime64(3){gcd_codec},
    group0_created_at DateTime64(3),
    group1_created_at DateTime64(3),
    group2_created_at DateTime64(3),
    group3_created_at DateTime64(3),
    group4_created_at DateTime64(3),
    inserted_at DateTime64(6, 'UTC') DEFAULT now64(){gcd_codec},
    person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2),
    consumer_breadcrumbs Array(String),
    historical_migration Bool,
    total_event_size UInt32{t64_codec},
    captured_at DateTime64(6, 'UTC') DEFAULT now(){gcd_codec},
    _partition UInt64{t64_codec}
{elements_columns}
{compatibility_columns}
{indexes}
) ENGINE = {engine}
"""


def EVENTS_JSON_TABLE_SQL(on_cluster: bool = False) -> str:
    return (
        EVENTS_JSON_TABLE_BASE_SQL
        + """PARTITION BY clamp(toYYYYMM(timestamp), 202001, 203512)
PRIMARY KEY (team_id, toDate(timestamp), event, cityHash64(distinct_id))
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), timestamp, uuid)
SAMPLE BY cityHash64(distinct_id)
SETTINGS index_granularity = 8192, object_serialization_version = 'v3', object_shared_data_serialization_version = 'map_with_buckets', enable_block_offset_column = 1, enable_block_number_column = 1, map_serialization_version = 'with_buckets', string_serialization_version = 'single_stream', propagate_types_serialization_versions_to_nested_types = 1
"""
    ).format(
        table_name=EVENTS_JSON_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=EVENTS_JSON_DATA_TABLE_ENGINE(),
        properties_json_type=EVENTS_PROPERTIES_JSON_TYPE(),
        person_properties_json_type=PERSON_PROPERTIES_JSON_TYPE(),
        temporary_properties_json_type=TEMPORARY_PROPERTIES_JSON_TYPE,
        temporary_properties_storage=" TTL toDateTime(inserted_at) + INTERVAL 60 DAY",
        gcd_codec=" CODEC(GCD, Default)",
        t64_codec=" CODEC(T64, Default)",
        elements_columns=EVENTS_JSON_ELEMENTS_COLUMNS,
        compatibility_columns="",
        indexes=EVENTS_JSON_DATA_TABLE_INDEXES(),
    )
