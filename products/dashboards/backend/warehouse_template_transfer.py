from __future__ import annotations

import re
from typing import Any

from posthog.models.resource_transfer.dashboard_template_views import copy_warehouse_views_by_name
from posthog.models.team.team import Team
from posthog.models.user import User


def collect_warehouse_table_names(node: Any) -> set[str]:
    """Recursively collect `DataWarehouseNode.table_name` values from a query JSON tree."""
    names: set[str] = set()
    if isinstance(node, dict):
        if node.get("kind") == "DataWarehouseNode":
            table_name = node.get("table_name")
            if isinstance(table_name, str) and table_name:
                names.add(table_name)
        for value in node.values():
            names |= collect_warehouse_table_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= collect_warehouse_table_names(item)
    return names


def copy_referenced_warehouse_views(
    *,
    tiles: list[Any],
    source_team: Team,
    target_team: Team,
    created_by: User,
) -> list[Any]:
    """Copy the data warehouse views a template's tiles read from into ``target_team``.

    Template tiles reference warehouse views by name (``DataWarehouseNode.table_name``), so a copied
    template's insights fail in another project unless the underlying views exist there too. We copy every
    referenced view — and its upstream view dependencies — into the target project. When a name collision
    there forces a ``_copy`` rename, the tile queries are rewritten to point at the new name so the
    reference still resolves.

    Returns the tiles, rewritten only where a referenced view was renamed on copy.
    """
    referenced_names: set[str] = set()
    for tile in tiles:
        if isinstance(tile, dict):
            referenced_names |= collect_warehouse_table_names(tile.get("query"))
    if not referenced_names:
        return tiles

    name_remap = copy_warehouse_views_by_name(
        view_names=referenced_names,
        source_team=source_team,
        target_team=target_team,
        created_by=created_by,
    )
    if not name_remap:
        return tiles
    return [_rewrite_tile_view_names(tile, name_remap) for tile in tiles]


def _rewrite_tile_view_names(tile: Any, name_remap: dict[str, str]) -> Any:
    if not isinstance(tile, dict):
        return tile
    query = tile.get("query")
    if not isinstance(query, dict):
        return tile
    return {**tile, "query": _rewrite_query_view_names(query, name_remap)}


def _rewrite_query_view_names(node: Any, name_remap: dict[str, str]) -> Any:
    if isinstance(node, dict):
        is_warehouse_node = node.get("kind") == "DataWarehouseNode"
        result: dict[str, Any] = {}
        for key, value in node.items():
            if is_warehouse_node and key == "table_name" and isinstance(value, str) and value in name_remap:
                result[key] = name_remap[value]
            elif key == "query" and isinstance(value, str):
                # Raw SQL nodes (e.g. HogQLQuery) reference views by name in the query text.
                result[key] = _rewrite_sql_identifiers(value, name_remap)
            else:
                result[key] = _rewrite_query_view_names(value, name_remap)
        return result
    if isinstance(node, list):
        return [_rewrite_query_view_names(item, name_remap) for item in node]
    return node


def _rewrite_sql_identifiers(sql: str, name_remap: dict[str, str]) -> str:
    result = sql
    for old_name, new_name in name_remap.items():
        # Replace whole-identifier occurrences only, so we don't touch substrings or column names.
        pattern = re.compile(rf"(?<![\w.]){re.escape(old_name)}(?![\w.])")
        result = pattern.sub(new_name, result)
    return result
