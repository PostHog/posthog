import logging
from datetime import timedelta
from functools import lru_cache

from posthog.cache_utils import cache_for
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.settings import CLICKHOUSE_DATABASE

logger = logging.getLogger(__name__)


def is_json_type(type_name: str) -> bool:
    normalized_type = type_name.strip()
    while normalized_type.startswith("Nullable(") or normalized_type.startswith("LowCardinality("):
        normalized_type = normalized_type[normalized_type.find("(") + 1 : -1].strip()
    return normalized_type == "JSON" or normalized_type.startswith("JSON(")


@cache_for(timedelta(minutes=15), background_refresh=True)
def get_clickhouse_column_type(table: str, column: str) -> str | None:
    if not table or any(character in table for character in "(). "):
        return None

    try:
        with tags_context(
            name="is_clickhouse_json_column",
            product=Product.INTERNAL,
            feature=Feature.SCHEMA_INTROSPECTION,
        ):
            rows = sync_execute(
                """
                SELECT type
                FROM system.columns
                WHERE database = %(database)s
                  AND table = %(table)s
                  AND name = %(column)s
                LIMIT 1
                """,
                {"database": CLICKHOUSE_DATABASE, "table": table.strip("`"), "column": column},
                ch_user=ClickHouseUser.META,
            )
    except Exception:
        logger.exception("Failed to detect ClickHouse JSON column. table=%s column=%s", table, column)
        return None

    return rows[0][0] if rows else None


def is_clickhouse_json_column(table: str, column: str) -> bool:
    type_name = get_clickhouse_column_type(table, column)
    return bool(type_name and is_json_type(type_name))


@lru_cache(maxsize=512)
def get_json_typed_paths(type_name: str) -> dict[str, str]:
    normalized_type = type_name.strip()
    if normalized_type == "JSON":
        return {}
    if not normalized_type.startswith("JSON(") or not normalized_type.endswith(")"):
        return {}

    arguments = _split_json_type_arguments(normalized_type[len("JSON(") : -1])
    typed_paths: dict[str, str] = {}
    for argument in arguments:
        parsed = _parse_json_path_definition(argument)
        if parsed is None:
            continue
        path, path_type = parsed
        typed_paths[path] = path_type
    return typed_paths


def is_clickhouse_json_typed_path(table: str, column: str, path_chain: tuple[str, ...]) -> bool:
    return get_clickhouse_json_typed_path_type(table, column, path_chain) is not None


def get_clickhouse_json_typed_path_type(table: str, column: str, path_chain: tuple[str, ...]) -> str | None:
    type_name = get_clickhouse_column_type(table, column)
    if not type_name:
        return None
    return get_json_typed_paths(type_name).get(".".join(path_chain))


def _split_json_type_arguments(arguments: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_backticks = False
    index = 0
    while index < len(arguments):
        character = arguments[index]
        if character == "`":
            in_backticks = not in_backticks
            current.append(character)
        elif not in_backticks and character == "(":
            depth += 1
            current.append(character)
        elif not in_backticks and character == ")":
            depth -= 1
            current.append(character)
        elif not in_backticks and depth == 0 and character == ",":
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    if current:
        parts.append("".join(current).strip())
    return parts


def _parse_json_path_definition(argument: str) -> tuple[str, str] | None:
    argument = argument.strip()
    if not argument or "=" in argument:
        return None

    if argument.startswith("`"):
        path, end_index = _parse_backtick_json_path(argument)
        path_type = argument[end_index:].strip()
    else:
        pieces = argument.split(None, 1)
        if len(pieces) != 2:
            return None
        path, path_type = pieces[0], pieces[1].strip()

    if not path or not path_type:
        return None
    return path, path_type


def _parse_backtick_json_path(argument: str) -> tuple[str, int]:
    path_characters: list[str] = []
    index = 1
    while index < len(argument):
        character = argument[index]
        if character == "`":
            if index + 1 < len(argument) and argument[index + 1] == "`":
                path_characters.append("`")
                index += 2
                continue
            return "".join(path_characters), index + 1
        path_characters.append(character)
        index += 1

    return "".join(path_characters), index
