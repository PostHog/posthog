import json
from pathlib import Path

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS


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


BOT_DEFINITIONS_FILE = (
    Path(__file__).resolve().parents[3]
    / "posthog"
    / "clickhouse"
    / "schema"
    / "catalog"
    / "web_bot_definition"
    / "web_bot_definitions.jsonl"
)


def bot_definitions_file_content() -> str:
    """The rows of the web_bot_definition table, one JSONCompactEachRow line each."""
    return "".join(json.dumps(list(row), ensure_ascii=False) + "\n" for row in _bot_definition_rows())
