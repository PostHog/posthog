"""Stable structural fingerprint of a HogQL query.

The fingerprint hashes the shape of an AST: node kinds, table and column references, function names,
operators, join kinds and aliases. It skips constant values, source positions and resolved types. Two
queries that differ only in literals (a date range, an event name, a LIMIT) share a fingerprint. Two
queries that differ in structure never do.

The HogQL executor emits it as the ``plan_fingerprint`` query tag, and ``query_log_archive`` exposes it
as ``lc_plan_fingerprint``. That lets the cost planner group the actual cost ClickHouse reports by plan
shape, and join it to the estimate it recorded for the same query.
"""

import hashlib
from collections.abc import Iterator
from dataclasses import fields
from enum import Enum

from pydantic import BaseModel

from posthog.hogql import ast
from posthog.hogql.base import AST, Type

# Source positions and the types the resolver attaches carry no structure.
_SKIPPED_FIELDS = frozenset({"start", "end", "type"})

_field_names_cache: dict[type, tuple[str, ...]] = {}


def _field_names(cls: type) -> tuple[str, ...]:
    names = _field_names_cache.get(cls)
    if names is None:
        names = tuple(f.name for f in fields(cls) if f.name not in _SKIPPED_FIELDS)
        _field_names_cache[cls] = names
    return names


def _tokens(value: object) -> Iterator[str]:
    if isinstance(value, ast.Constant):
        # The literal's type shapes the plan (a string vs a number comparison); its value does not.
        yield f"Constant:{type(value.value).__name__}"
    elif isinstance(value, ast.Alias) and value.hidden:
        # The resolver adds hidden aliases to name columns. They are not part of the query's shape.
        yield from _tokens(value.expr)
    elif isinstance(value, Type):
        return
    elif isinstance(value, AST):
        yield type(value).__name__
        for name in _field_names(type(value)):
            yield name
            yield from _tokens(getattr(value, name))
        yield "/"
    elif isinstance(value, list | tuple):
        yield "["
        for item in value:
            yield from _tokens(item)
        yield "]"
    elif isinstance(value, dict):
        yield "{"
        for key, item in value.items():
            yield str(key)
            yield from _tokens(item)
        yield "}"
    elif isinstance(value, BaseModel):
        # Query settings such as join_algorithm change the physical plan, so every set value is part of
        # the shape. Unset fields are skipped so adding a new setting does not move existing fingerprints.
        yield type(value).__name__
        for name, item in sorted(value.model_dump(exclude_none=True).items()):
            yield name
            yield from _tokens(item)
        yield "/"
    elif isinstance(value, Enum):
        yield str(value.value)
    elif value is None or isinstance(value, str | int | float | bool):
        yield repr(value)
    else:
        yield type(value).__name__


def fingerprint_query(node: ast.SelectQuery | ast.SelectSetQuery) -> str:
    """Return a 16-hex-character digest of the query's structure."""
    digest = hashlib.sha256("\x1f".join(_tokens(node)).encode())
    return digest.hexdigest()[:16]
