"""Helpers for batch exports powered by a user-defined HogQL query.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import typing

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer import prepare_ast_for_printing

if typing.TYPE_CHECKING:
    from posthog.models import Team


class UnsupportedHogQLQueryError(Exception):
    """Raised when a HogQL query cannot be used to power a batch export."""


def parse_hogql_select_for_batch_export(hogql_query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse a HogQL SELECT query intended to power a batch export.

    Placeholders are not currently supported in batch exports, they will be coming soon...

    Raises:
        UnsupportedHogQLQueryError: If the query cannot be parsed as a SELECT or
            contains placeholders, which batch exports have no way to resolve.
        InternalHogQLError: Left to propagate. An internal HogQL engine error is our
            bug, not a problem with the user's query, so it should surface as an error
            (and get alerted on) rather than be reported back as an unsupported query.
    """
    try:
        parsed = parse_select(hogql_query)
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Failed to parse HogQL query: {e}") from e

    # TODO: support placeholder expressions in batch exports
    placeholders = find_placeholders(parsed)
    if placeholders.has_filters or placeholders.placeholder_fields or placeholders.placeholder_expressions:
        raise UnsupportedHogQLQueryError("Placeholders are not supported in batch export queries")

    return parsed


def create_hogql_context_for_batch_export(team: "Team", values: dict[str, typing.Any] | None = None) -> HogQLContext:
    """Build the HogQLContext batch exports use to resolve and print a query.

    Both API-side validation and worker-side execution must build the context the same
    way (team-default modifiers, full database, no top-level LIMIT), otherwise a query
    that validates could resolve differently when it runs. This builder is the single
    source of truth for those semantics. It reads from Postgres, so worker code must
    call it off the event loop.
    """
    context = HogQLContext(
        team=team,
        team_id=team.id,
        enable_select_queries=True,
        limit_top_select=False,
        values=values if values is not None else {},
    )
    context.database = Database.create_for(team=team, modifiers=context.modifiers)
    return context


def _validate_select_columns_are_named(parsed: ast.SelectQuery | ast.SelectSetQuery) -> None:
    """Check every top-level SELECT expression has a usable output column name.

    Bare fields and `*` name their columns; anything else (function calls, arithmetic,
    constants) prints as an expression, producing column names like `plus(1, 1)`, which are likely to
    cause issues in downstream destinations (e.g. BigQuery does not permit spaces in column names).

    We could relax this restriction in future and handle validation in the downstream destination.
    """
    select_query = parsed
    # In a set operation (e.g. UNION ALL) the first SELECT names the output columns.
    while isinstance(select_query, ast.SelectSetQuery):
        select_query = select_query.initial_select_query
    for expr in select_query.select:
        if not isinstance(expr, ast.Field | ast.Alias):
            raise UnsupportedHogQLQueryError(
                "Every column in the SELECT clause must be a field or have an alias (e.g. `count() AS event_count`)"
            )


def validate_hogql_query_for_batch_export(hogql_query: str, team: "Team") -> None:
    """Validate a HogQL query can power a batch export for the given team.

    Parses the query, checks output columns are named, and resolves types against the
    team's database (catching unknown tables/fields) with the same context the worker
    will execute with.

    Raises:
        UnsupportedHogQLQueryError: If the query cannot power a batch export.
        InternalHogQLError: Left to propagate, as in `parse_hogql_select_for_batch_export`.
    """
    parsed = parse_hogql_select_for_batch_export(hogql_query)
    _validate_select_columns_are_named(parsed)

    context = create_hogql_context_for_batch_export(team)
    try:
        prepare_ast_for_printing(parsed, context=context, dialect="clickhouse", stack=[])
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Invalid HogQL query: {e}") from e
