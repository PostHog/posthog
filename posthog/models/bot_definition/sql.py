from posthog.clickhouse.table_engines import MergeTreeEngine, ReplicationScheme
from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from posthog.settings import CLICKHOUSE_PASSWORD

BOT_DEFINITION_TABLE_NAME = "web_bot_definition"
BOT_DEFINITION_DICTIONARY_NAME = "web_bot_definition_dict"

BOT_DEFINITION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id UInt64,
    parent_id UInt64,
    regexp String,
    keys Array(String),
    values Array(String)
) ENGINE = {engine}
ORDER BY id
""".format(
    table_name=BOT_DEFINITION_TABLE_NAME,
    engine=MergeTreeEngine(BOT_DEFINITION_TABLE_NAME, replication_scheme=ReplicationScheme.REPLICATED),
)

DROP_BOT_DEFINITION_TABLE_SQL = f"DROP TABLE IF EXISTS {BOT_DEFINITION_TABLE_NAME} SYNC"

DROP_BOT_DEFINITION_DICTIONARY_SQL = f"DROP DICTIONARY IF EXISTS {BOT_DEFINITION_DICTIONARY_NAME}"


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


def _format_array(values: list[str]) -> str:
    escaped = ", ".join(f"'{v.replace(chr(39), chr(39) + chr(39))}'" for v in values)
    return f"[{escaped}]"


def _format_pattern(pattern: str) -> str:
    return pattern.replace("'", "''")


BOT_DEFINITION_DATA_SQL = """
INSERT INTO {table_name} (id, parent_id, regexp, keys, values) VALUES
{rows}
""".format(
    table_name=BOT_DEFINITION_TABLE_NAME,
    rows=",\n".join(
        f"({row[0]}, {row[1]}, '{_format_pattern(row[2])}', {_format_array(row[3])}, {_format_array(row[4])})"
        for row in _bot_definition_rows()
    ),
)

BOT_DEFINITION_DICTIONARY_SQL = f"""
CREATE DICTIONARY IF NOT EXISTS {BOT_DEFINITION_DICTIONARY_NAME} (
    regexp String,
    name String,
    category String,
    traffic_type String,
    operator String
)
PRIMARY KEY regexp
SOURCE(CLICKHOUSE(TABLE '{BOT_DEFINITION_TABLE_NAME}' PASSWORD '{CLICKHOUSE_PASSWORD}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(REGEXP_TREE())
"""

# Lambda UDFs for direct SQL editor usage — these provide stable callable names
# that delegate to the dictionary, decoupling query authors from dict internals.
BOT_DEFINITION_UDFS_SQL = [
    "CREATE FUNCTION IF NOT EXISTS botGetName AS (ua) -> dictGetOrDefault('{dict}', 'name', ua, '')",
    "CREATE FUNCTION IF NOT EXISTS botGetCategory AS (ua) -> dictGetOrDefault('{dict}', 'category', ua, 'regular')",
    "CREATE FUNCTION IF NOT EXISTS botGetTrafficType AS (ua) -> dictGetOrDefault('{dict}', 'traffic_type', ua, 'Regular')",
    "CREATE FUNCTION IF NOT EXISTS botGetOperator AS (ua) -> dictGetOrDefault('{dict}', 'operator', ua, '')",
    # isBot: any non-Regular traffic type (AI Agent, Bot, Automation) means the UA is a bot
    "CREATE FUNCTION IF NOT EXISTS botIsBot AS (ua) -> dictGetOrDefault('{dict}', 'traffic_type', ua, 'Regular') != 'Regular'",
]

DROP_BOT_DEFINITION_UDFS_SQL = [
    "DROP FUNCTION IF EXISTS botGetName",
    "DROP FUNCTION IF EXISTS botGetCategory",
    "DROP FUNCTION IF EXISTS botGetTrafficType",
    "DROP FUNCTION IF EXISTS botGetOperator",
    "DROP FUNCTION IF EXISTS botIsBot",
]
