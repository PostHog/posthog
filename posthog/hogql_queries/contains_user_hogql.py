"""Detect whether a query embeds user-authored HogQL, from the query schema alone.

The parse-site tagging in `tag_contains_user_hogql()` only fires once a user-HogQL
string actually reaches a `parse_expr`/`parse_select` call. A query that throws
*before* that point (validation, an early `QueryError`, an exception raised mid-parse)
never sets the tag, so `contains_user_hogql=false` historically meant "we never hit a
parse site", not "no user HogQL was involved".

This module determines the answer up front from the query structure, so the flag is
reliable regardless of where execution fails. It is the source of truth; the parse-site
calls remain as a defense-in-depth backstop.
"""

from typing import Any

from pydantic import BaseModel

# Marker fields, checked per node. Each is the canonical site where a user-controlled
# HogQL string is handed to the parser (mirrors every `tag_contains_user_hogql()` call).
_HOGQL_STRING_FIELDS = (
    "query",  # HogQLQuery.query (SQL editor)
    "pathsHogQLExpression",  # PathsFilter
)
_HOGQL_LIST_FIELDS = (
    "select",  # EventsQuery / ActorsQuery / SessionsQuery
    "orderBy",
)


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list | tuple):
        return len(value) > 0
    return bool(value)


def _node_has_user_hogql(node: BaseModel) -> bool:
    data = node.__dict__

    # HogQLPropertyFilter: a property whose type is "hogql" carries a user HogQL key.
    if data.get("type") == "hogql" and _is_nonempty(data.get("key")):
        return True

    # math == "hogql" on a series node (EventsNode / ActionsNode / DataWarehouseNode).
    if data.get("math") == "hogql" and _is_nonempty(data.get("math_hogql")):
        return True

    # BreakdownFilter with a HogQL breakdown.
    if data.get("breakdown_type") == "hogql" and _is_nonempty(data.get("breakdown")):
        return True

    # EventsQuery.where is a single user HogQL string (select/orderBy handled below as lists).
    if _is_nonempty(data.get("where")):
        return True

    # Data warehouse nodes (DataWarehouseNode, FunnelsDataWarehouseNode,
    # LifecycleDataWarehouseNode, ExperimentDataWarehouseNode) carry user-HogQL field
    # expressions that are parsed verbatim.
    kind = data.get("kind")
    if (
        isinstance(kind, str)
        and kind.endswith("DataWarehouseNode")
        and any(
            _is_nonempty(data.get(f))
            for f in ("timestamp_field", "distinct_id_field", "id_field", "data_warehouse_join_key")
        )
    ):
        return True

    for field in _HOGQL_STRING_FIELDS:
        if _is_nonempty(data.get(field)) and isinstance(data.get(field), str):
            return True

    for field in _HOGQL_LIST_FIELDS:
        value = data.get(field)
        if isinstance(value, list) and any(isinstance(v, str) and v.strip() for v in value):
            return True

    return False


def contains_user_hogql(query: Any) -> bool:
    """Recursively walk a query model; True if any node embeds user-authored HogQL.

    Pure schema inspection — no parsing, no execution — so it is safe to call before
    running the query and cannot itself raise on bad user HogQL.
    """
    seen: set[int] = set()

    def walk(obj: Any) -> bool:
        if isinstance(obj, BaseModel):
            if id(obj) in seen:
                return False
            seen.add(id(obj))
            if _node_has_user_hogql(obj):
                return True
            return any(walk(v) for v in obj.__dict__.values())
        if isinstance(obj, dict):
            return any(walk(v) for v in obj.values())
        if isinstance(obj, list | tuple):
            return any(walk(v) for v in obj)
        return False

    return walk(query)
