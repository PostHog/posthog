from django.conf import settings

from posthog.clickhouse.dictionaries import dictionary_source_clickhouse
from posthog.clickhouse.table_engines import Distributed, MergeTreeEngine, ReplicationScheme

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS

# Topology mirrors the web-analytics preaggregated tables:
#   - sharded_web_bot_definition holds the data and lives only on the AUX cluster.
#   - web_bot_definition is a Distributed read table on DATA + AUX that resolves to the
#     AUX-resident data via cluster=AUX.
# DATA and AUX have separate ZooKeeper, so creating a same-named ReplicatedMergeTree on
# each cluster would produce two unrelated tables that silently diverge; routing reads
# through one AUX data table avoids that.
SHARDED_BOT_DEFINITION_TABLE_NAME = "sharded_web_bot_definition"
BOT_DEFINITION_TABLE_NAME = "web_bot_definition"
BOT_DEFINITION_DICTIONARY_NAME = "web_bot_definition_dict"

# REGEXP_TREE source columns: keys/values carry the per-pattern attributes the dict
# exposes (name, category, traffic_type, operator).
BOT_DEFINITION_TABLE_COLUMNS = """
    id UInt64,
    parent_id UInt64,
    regexp String,
    keys Array(String),
    values Array(String)
"""

SHARDED_BOT_DEFINITION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
{columns}
) ENGINE = {engine}
ORDER BY id
""".format(
    table_name=SHARDED_BOT_DEFINITION_TABLE_NAME,
    columns=BOT_DEFINITION_TABLE_COLUMNS,
    engine=MergeTreeEngine(SHARDED_BOT_DEFINITION_TABLE_NAME, replication_scheme=ReplicationScheme.SHARDED),
)

BOT_DEFINITION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
{columns}
) ENGINE = {engine}
""".format(
    table_name=BOT_DEFINITION_TABLE_NAME,
    columns=BOT_DEFINITION_TABLE_COLUMNS,
    engine=Distributed(
        data_table=SHARDED_BOT_DEFINITION_TABLE_NAME,
        sharding_key="sipHash64(id)",
        cluster=settings.CLICKHOUSE_AUX_CLUSTER,
    ),
)

DROP_SHARDED_BOT_DEFINITION_TABLE_SQL = f"DROP TABLE IF EXISTS {SHARDED_BOT_DEFINITION_TABLE_NAME} SYNC"

DROP_BOT_DEFINITION_TABLE_SQL = f"DROP TABLE IF EXISTS {BOT_DEFINITION_TABLE_NAME}"

DROP_BOT_DEFINITION_DICTIONARY_SQL = f"DROP DICTIONARY IF EXISTS {BOT_DEFINITION_DICTIONARY_NAME}"

# BOT_DEFINITIONS in Python is the single source of truth. Every migration that seeds bot data
# should TRUNCATE first so re-runs and content updates produce a clean table that matches what's
# currently in BOT_DEFINITIONS, with no leftover rows from previous shapes.
TRUNCATE_BOT_DEFINITION_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS {SHARDED_BOT_DEFINITION_TABLE_NAME}"


def _bot_definition_rows() -> list[tuple[int, int, str, list[str], list[str]]]:
    """Build rows for the REGEXP_TREE table from BOT_DEFINITIONS."""
    rows = []
    for i, (pattern, bot) in enumerate(BOT_DEFINITIONS.items(), start=1):
        rows.append(
            (
                i,
                0,
                pattern,
                ["name", "category", "traffic_type", "operator"],
                [bot.name, bot.category, bot.traffic_type, bot.operator],
            )
        )
    # Empty UA row — ^$ matches empty string, classified as Automation/no_user_agent
    rows.append(
        (
            len(rows) + 1,
            0,
            "^$",
            ["name", "category", "traffic_type", "operator"],
            ["", "no_user_agent", "Automation", ""],
        )
    )
    return rows


def _escape_sql_string(s: str) -> str:
    # Escape backslashes before quotes — ClickHouse treats \X as an escape sequence in string literals,
    # so r"desktop\.hog\.dev" would silently become "desktop.hog.dev" (broader regex) without this.
    return s.replace("\\", "\\\\").replace("'", "''")


def _format_array(values: list[str]) -> str:
    escaped = ", ".join(f"'{_escape_sql_string(v)}'" for v in values)
    return f"[{escaped}]"


def _format_pattern(pattern: str) -> str:
    return _escape_sql_string(pattern)


BOT_DEFINITION_DATA_SQL = """
INSERT INTO {table_name} (id, parent_id, regexp, keys, values) VALUES
{rows}
""".format(
    table_name=SHARDED_BOT_DEFINITION_TABLE_NAME,
    rows=",\n".join(
        f"({row[0]}, {row[1]}, '{_format_pattern(row[2])}', {_format_array(row[3])}, {_format_array(row[4])})"
        for row in _bot_definition_rows()
    ),
)

# Sources from the Distributed read table so the dict resolves identically on DATA and AUX.
BOT_DEFINITION_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {BOT_DEFINITION_DICTIONARY_NAME} (
    regexp String,
    name String,
    category String,
    traffic_type String,
    operator String
)
PRIMARY KEY regexp
{dictionary_source_clickhouse(BOT_DEFINITION_TABLE_NAME)}
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(REGEXP_TREE())
"""


# Bot-detection UDFs. Names are namespaced (`webAnalytics*`) because ClickHouse functions share
# one global catalog — a generic `isBot`/`botName` would risk clashing with built-ins or other
# products. Bodies use multiMatchAnyIndex (Hyperscan), NOT the REGEXP_TREE dict's dictGet:
# benchmarks on real traffic showed dictGet costs 7-46x more CPU and grows with row count, while
# multiMatch stays flat (~200 ms at any window). SQL UDFs are macro-expanded at query-analysis
# time, so call sites stay tiny (`webAnalyticsBotName(ua)`) yet execute at full multiMatch speed.
# BOT_DEFINITIONS remains the single source of truth — the same patterns/labels the dict is
# seeded from and the inline HogQL path emits.
_BOT_UDF_PATTERNS = _format_array([*BOT_DEFINITIONS.keys(), "^$"])


def _bot_udf_label_lookup(attr: str, default: str, empty_ua_value: str) -> str:
    # Label array aligns with the patterns array: [default, <per-bot attr>…, empty_ua_value].
    # multiMatchAnyIndex returns 0 (no match) or 1..N+1 ("^$" is N+1); arrayElement(arr, idx + 1)
    # then maps 0 -> default, k -> attr of bot k, N+1 -> empty_ua_value.
    labels = [default, *(getattr(bot, attr) for bot in BOT_DEFINITIONS.values()), empty_ua_value]
    return f"arrayElement({_format_array(labels)}, multiMatchAnyIndex(ifNull(ua, ''), {_BOT_UDF_PATTERNS}) + 1)"


BOT_DEFINITION_UDF_NAMES = [
    "webAnalyticsIsBot",
    "webAnalyticsBotName",
    "webAnalyticsBotCategory",
    "webAnalyticsBotTrafficType",
    "webAnalyticsBotOperator",
]

# CREATE OR REPLACE so a later BOT_DEFINITIONS change re-creates the functions idempotently via a
# follow-up migration. Defaults mirror the inline HogQL builder (traffic_type.py).
BOT_DEFINITION_UDFS_SQL = [
    f"CREATE OR REPLACE FUNCTION webAnalyticsIsBot AS (ua) -> multiMatchAny(ifNull(ua, ''), {_BOT_UDF_PATTERNS})",
    f"CREATE OR REPLACE FUNCTION webAnalyticsBotName AS (ua) -> {_bot_udf_label_lookup('name', '', '')}",
    f"CREATE OR REPLACE FUNCTION webAnalyticsBotCategory AS (ua) -> {_bot_udf_label_lookup('category', 'regular', 'no_user_agent')}",
    f"CREATE OR REPLACE FUNCTION webAnalyticsBotTrafficType AS (ua) -> {_bot_udf_label_lookup('traffic_type', 'Regular', 'Automation')}",
    f"CREATE OR REPLACE FUNCTION webAnalyticsBotOperator AS (ua) -> {_bot_udf_label_lookup('operator', '', '')}",
]

DROP_BOT_DEFINITION_UDFS_SQL = [f"DROP FUNCTION IF EXISTS {name}" for name in BOT_DEFINITION_UDF_NAMES]
