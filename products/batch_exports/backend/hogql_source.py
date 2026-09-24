"""Helpers for batch exports powered by a user-defined HogQL query.

This module must stay importable by both the API layer and the Temporal worker, so it
should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import typing
import datetime as dt

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.events_json import UNPARSEABLE_PROPERTIES_KEY

if typing.TYPE_CHECKING:
    from posthog.models import Team, User

    from products.batch_exports.backend.service import BatchExportField, BatchExportSchema

DATA_INTERVAL_START_PLACEHOLDER = "data_interval_start"
DATA_INTERVAL_END_PLACEHOLDER = "data_interval_end"

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
    data_interval_end: dt.datetime | None,
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Return a copy of the query with the interval placeholders replaced by their values.

    A referenced bound must have a value, including for beginning-of-time backfills.
    The input query is not modified.
    """
    bounds = {
        DATA_INTERVAL_START_PLACEHOLDER: data_interval_start,
        DATA_INTERVAL_END_PLACEHOLDER: data_interval_end,
    }
    for name in sorted(find_interval_placeholders(parsed)):
        if bounds[name] is None:
            raise UnsupportedHogQLQueryError(
                f"The query references '{{{name}}}', but '{name}' is not defined. "
                "Provide the bound or remove the placeholder from the query."
            )

    return typing.cast(
        ast.SelectQuery | ast.SelectSetQuery,
        replace_placeholders(
            parsed,
            {name: ast.Constant(value=value) for name, value in bounds.items() if value is not None},
        ),
    )


def validate_hogql_batch_export_user(team: "Team", user: "User | None") -> None:
    from posthog.models import User  # noqa: PLC0415 - keeps Django models off the worker import path
    from posthog.user_permissions import UserPermissions  # noqa: PLC0415 - requires initialized Django models

    if not isinstance(user, User) or not user.is_active:
        raise UnsupportedHogQLQueryError(
            "This HogQL export needs an active user. Save the export again with a user who has access to this project."
        )
    if UserPermissions(user=user, team=team).current_team.effective_membership_level is None:
        raise UnsupportedHogQLQueryError(
            "The user who saved this HogQL export no longer has access to this project. "
            "Save the export again with a user who has access."
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
    context.database = Database.create_for(team=team, user=user, modifiers=context.modifiers)
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


def validate_hogql_query_for_batch_export(hogql_query: str, team: "Team", *, user: "User") -> None:
    """Validate a HogQL query can power a batch export for the given team.

    Parses the query, checks output columns are named, and compiles it with the user's
    table and property permissions using the same context the worker
    will execute with. Resolution runs on the query with any interval placeholders
    substituted, exactly as a run does, so misuse that breaks resolution is caught
    here instead of failing every run. A query without placeholders is equally valid:
    it runs as-is, so every run exports all rows the query returns at run time.

    Raises:
        UnsupportedHogQLQueryError: If the query cannot power a batch export.
        InternalHogQLError: Left to propagate, as in `parse_hogql_select_for_batch_export`.
    """
    validate_hogql_batch_export_user(team, user)
    parsed = parse_hogql_select_for_batch_export(hogql_query)
    _validate_select_columns_are_named(parsed)

    parsed = replace_interval_placeholders(parsed, _VALIDATION_DATA_INTERVAL_START, _VALIDATION_DATA_INTERVAL_END)

    context = create_hogql_context_for_batch_export(team, user=user)
    try:
        prepared = prepare_ast_for_printing(parsed, context=context, dialect="clickhouse", stack=[])
        assert prepared is not None
        print_prepared_ast(prepared, context=context, dialect="clickhouse", stack=[])
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Invalid HogQL query: {e}") from e


class SerializedExportProperties(CloningVisitor):
    """Rebind event fields while preserving property access restrictions."""

    def __init__(self, table_alias: str, context: HogQLContext) -> None:
        super().__init__()
        self.table_alias = table_alias

        from products.access_control.backend.facade.api import (  # noqa: PLC0415 — keeps Django access-control imports off the batch worker import path
            split_restricted_property_names,
        )

        restrictions = context.restricted_properties or set()
        restricted_names = split_restricted_property_names(restrictions)
        self.event_restrictions = set(restricted_names.event)
        self.person_restrictions = set(restricted_names.person)
        if restrictions and context.uses_new_events_schema():
            self.event_restrictions.add(UNPARSEABLE_PROPERTIES_KEY)
            self.person_restrictions.add(UNPARSEABLE_PROPERTIES_KEY)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        node = super().visit_field(node)
        if node.chain[0] == self.table_alias:
            node.chain[0] = "events"
        index = 1 if node.chain[0] == "events" else 0
        if len(node.chain) <= index:
            return node
        if node.chain[index : index + 2] == ["person", "properties"]:
            # `poe.properties` is the events table's own copy of the person properties.
            node.chain[index : index + 2] = ["poe", "properties"]
        if node.chain[index : index + 2] == ["poe", "properties"]:
            restrictions, property_chain = self.person_restrictions, node.chain[index + 2 :]
        elif str(node.chain[index]) == "properties":
            restrictions, property_chain = self.event_restrictions, node.chain[index + 1 :]
        else:
            return node
        if restrictions:
            property_path = ".".join(str(part) for part in property_chain)
            if not property_path:
                raise QueryError("Batch export queries cannot select a restricted properties object")
            if any(
                property_path == key or property_path.startswith(key + ".") or key.startswith(property_path + ".")
                for key in restrictions
            ):
                return ast.Constant(value=None)
        return node


def prepare_serialized_export_query(query: ast.SelectQuery, context: HogQLContext) -> ast.SelectQuery:
    """Resolve a HogQL query the way the export SQL reads it."""
    assert query.select_from is not None
    query = SerializedExportProperties(query.select_from.alias or "events", context).visit(query)
    assert query.select_from is not None
    # The export SQL names its source `events`, so a user alias must not reach the printed fields.
    query.select_from.alias = None
    # Every export template hands the fields a String `properties`, the native source included, so
    # the legacy shape is the one form valid on both. Resolving against the events table rather than
    # a subquery is also what lets the swapper keep the cast a typed property needs.
    context.use_new_events_schema = False
    return typing.cast(ast.SelectQuery, prepare_ast_for_printing(query, context=context, dialect="clickhouse"))


def serialize_batch_export_query(query: ast.SelectQuery, context: HogQLContext) -> "BatchExportSchema":
    """Compile a HogQL query into stable ClickHouse expressions and aliases."""
    if context.uses_new_events_schema():
        hogql = print_prepared_ast(query, context=context, dialect="hogql")
        query = prepare_serialized_export_query(typing.cast(ast.SelectQuery, parse_select(hogql)), context)
        stack = [query]
    else:
        print_prepared_ast(query, context=context, dialect="clickhouse")
        context = HogQLContext(
            team_id=context.team_id,
            enable_select_queries=True,
            limit_top_select=False,
            use_new_events_schema=False,
        )
        stack = []
        hogql = print_prepared_ast(query, context=context, dialect="hogql")
    fields: list[BatchExportField] = []
    for field in query.select:
        if isinstance(field, ast.Alias):
            expression = print_prepared_ast(field.expr, context=context, dialect="clickhouse", stack=stack)
            alias = escape_clickhouse_identifier(field.alias)
        else:
            expression = print_prepared_ast(field, context=context, dialect="clickhouse", stack=stack)
            # String constants get parameterized by the ClickHouse printer (e.g., 'hello' becomes
            # %(hogql_val_0)s), which escape_clickhouse_identifier rejects. Use the raw value instead.
            alias = escape_clickhouse_identifier(
                field.value if isinstance(field, ast.Constant) and isinstance(field.value, str) else expression
            )
        fields.append({"expression": expression, "alias": alias})
    return {"fields": fields, "values": context.values, "hogql_query": hogql}
