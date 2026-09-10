"""Helpers for batch exports powered by a user-defined HogQL query.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import typing
import datetime as dt

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing

if typing.TYPE_CHECKING:
    from posthog.models import Team, User

DATA_INTERVAL_START_PLACEHOLDER = "data_interval_start"
DATA_INTERVAL_END_PLACEHOLDER = "data_interval_end"

# For queries that just want the whole range, like beginning-of-time backfills.
DATA_INTERVAL_START_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

# When validating a query, we need to fill-in some values. Any values would
# work, these are just arbitrary.
_VALIDATION_DATA_INTERVAL_START = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)
_VALIDATION_DATA_INTERVAL_END = dt.datetime(2000, 1, 2, tzinfo=dt.UTC)

_SUPPORTED_PLACEHOLDERS = f"{{{DATA_INTERVAL_START_PLACEHOLDER}}} and {{{DATA_INTERVAL_END_PLACEHOLDER}}}"


class UnsupportedHogQLQueryError(Exception):
    """Raised when a HogQL query cannot be used to power a batch export."""


def parse_hogql_select_for_batch_export(hogql_query: str) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse a HogQL SELECT query intended to power a batch export.

    Only the `{data_interval_start}` and `{data_interval_end}` placeholders are supported, as
    those are the ones a run can resolve with its data interval bounds.

    Raises:
        UnsupportedHogQLQueryError: If the query cannot be parsed as a SELECT or contains
            placeholders other than the two interval ones.
        InternalHogQLError: Left to propagate. An internal HogQL engine error is our
            bug, not a problem with the user's query, so it should surface as an error
            (and get alerted on) rather than be reported back as an unsupported query.
    """
    try:
        parsed = parse_select(hogql_query)
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Failed to parse HogQL query: {e}") from e

    placeholders = find_placeholders(parsed)
    if placeholders.has_filters or placeholders.placeholder_expressions:
        raise UnsupportedHogQLQueryError(
            f"Unsupported placeholder. Only {_SUPPORTED_PLACEHOLDERS} are supported in batch export queries"
        )
    for chain in placeholders.placeholder_fields:
        if chain not in ([DATA_INTERVAL_START_PLACEHOLDER], [DATA_INTERVAL_END_PLACEHOLDER]):
            name = ".".join(str(part) for part in chain)
            raise UnsupportedHogQLQueryError(
                f"Unknown placeholder '{{{name}}}'. "
                f"Only {_SUPPORTED_PLACEHOLDERS} are supported in batch export queries"
            )

    return parsed


def find_interval_placeholders(parsed: ast.SelectQuery | ast.SelectSetQuery) -> set[str]:
    """Return the names of interval placeholders the query references."""
    chains = find_placeholders(parsed).placeholder_fields
    names: set[str] = set()
    if [DATA_INTERVAL_START_PLACEHOLDER] in chains:
        names.add(DATA_INTERVAL_START_PLACEHOLDER)
    if [DATA_INTERVAL_END_PLACEHOLDER] in chains:
        names.add(DATA_INTERVAL_END_PLACEHOLDER)
    return names


def replace_interval_placeholders(
    parsed: ast.SelectQuery | ast.SelectSetQuery,
    data_interval_start: dt.datetime | None,
    data_interval_end: dt.datetime,
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Return a copy of the query with the interval placeholders replaced by their values.

    A `None` start substitutes the epoch sentinel, so a `field >= {data_interval_start}`
    predicate keeps matching every row in a backfill from the beginning of time.

    The input query is not modified.
    """
    return typing.cast(
        ast.SelectQuery | ast.SelectSetQuery,
        replace_placeholders(
            parsed,
            {
                DATA_INTERVAL_START_PLACEHOLDER: ast.Constant(
                    value=data_interval_start if data_interval_start is not None else DATA_INTERVAL_START_EPOCH
                ),
                DATA_INTERVAL_END_PLACEHOLDER: ast.Constant(value=data_interval_end),
            },
        ),
    )


def create_hogql_context_for_batch_export(
    team: "Team", values: dict[str, typing.Any] | None = None, user: "User | None" = None
) -> HogQLContext:
    """Build the HogQLContext batch exports use to resolve and print a query.

    Both API-side validation and worker-side execution must build the context the same
    way, otherwise a query that validates could resolve differently when it runs. This
    builder is the single source of truth for those semantics: the database is built
    with team-default modifiers, the context keeps plain default modifiers for printing
    (`Database.create_for` team-defaults a copy, not this context's instance), and no
    top-level LIMIT is applied. It reads from Postgres, so worker code must call it off
    the event loop.
    """
    context = HogQLContext(
        team=team,
        team_id=team.id,
        user=user,
        enable_select_queries=True,
        limit_top_select=False,
        values=values if values is not None else {},
        modifiers=create_default_modifiers_for_team(team),
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


def validate_hogql_query_for_batch_export(hogql_query: str, team: "Team", user: "User | None" = None) -> None:
    """Validate a HogQL query can power a batch export for the given team.

    Parses the query, checks output columns are named, and resolves types against the
    team's database (catching unknown tables/fields) with the same context the worker
    will execute with. Resolution runs on the query with any interval placeholders
    substituted, exactly as a run does, so misuse that breaks resolution is caught
    here instead of failing every run. A query without placeholders is equally valid:
    it runs as-is, so every run exports all rows the query returns at run time.

    Raises:
        UnsupportedHogQLQueryError: If the query cannot power a batch export.
        InternalHogQLError: Left to propagate, as in `parse_hogql_select_for_batch_export`.
    """
    parsed = parse_hogql_select_for_batch_export(hogql_query)
    _validate_select_columns_are_named(parsed)

    parsed = replace_interval_placeholders(parsed, _VALIDATION_DATA_INTERVAL_START, _VALIDATION_DATA_INTERVAL_END)

    context = create_hogql_context_for_batch_export(team, user=user)
    try:
        prepare_ast_for_printing(parsed, context=context, dialect="clickhouse", stack=[])
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Invalid HogQL query: {e}") from e
