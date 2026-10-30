"""The legacy custom events schema: an events model export that selects its fields with a limited HogQL query.

The API checks the query and stores it as a schema of ClickHouse expressions. Runs recompile the
stored query when they read the native events table. New exports use the HogQL model in
`hogql_source` instead. This module must stay importable by both the API layer and the Temporal
worker, so it should not import from `products.batch_exports.backend.temporal` or any DRF code.
"""

import typing

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import contains_subquery
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.clickhouse.events_json import UNPARSEABLE_PROPERTIES_KEY

from products.batch_exports.backend.facade.contracts import UnsupportedHogQLQueryError
from products.batch_exports.backend.facade.enums import EXPORTABLE_EVENTS_MODEL_FIELDS

if typing.TYPE_CHECKING:
    from posthog.models import User

    from products.batch_exports.backend.service import BatchExportField, BatchExportSchema


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


def recompile_stored_schema(
    team_id: int, schema: "BatchExportSchema", hogql_query: str
) -> tuple[list["BatchExportField"], dict[str, typing.Any]]:
    """Recompile the stored query of a schema for the native events table, keeping the stored aliases.

    Returns the fields and the query values a run sends with them.
    """
    context = HogQLContext(
        team_id=team_id,
        enable_select_queries=True,
        limit_top_select=False,
        modifiers=HogQLQueryModifiers(
            materializationMode=MaterializationMode.DISABLED,
            personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        ),
    )
    compiled = serialize_batch_export_query(typing.cast(ast.SelectQuery, parse_select(hogql_query)), context)
    fields: list[BatchExportField] = [
        {"expression": compiled_field["expression"], "alias": stored_field["alias"]}
        for stored_field, compiled_field in zip(schema["fields"], compiled["fields"], strict=True)
    ]
    return fields, compiled["values"]


def parse_events_hogql_query(
    hogql_query: str, team_id: int, user: "User | None"
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Parse a HogQL SelectQuery from a string query."""
    from products.access_control.backend.facade.api import (  # noqa: PLC0415 — keeps Django access-control imports off the batch worker import path
        get_restricted_properties_with_group_type_index_for_team,
    )

    try:
        parsed_query = parse_select(hogql_query)
    except Exception:
        raise UnsupportedHogQLQueryError("Failed to parse query")

    try:
        restricted_properties = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
        context = HogQLContext(
            team_id=team_id,
            user=user,
            enable_select_queries=True,
            restricted_properties=restricted_properties,
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        if restricted_properties:
            # A restricted query is stored without its HogQL text, so no run can recompile it for
            # the native source, where a materialized column does not exist.
            context.modifiers.materializationMode = MaterializationMode.DISABLED
        use_native_schema = context.uses_new_events_schema()
        prepared_select_query = typing.cast(
            ast.SelectQuery,
            prepare_ast_for_printing(
                parsed_query, context=context, dialect="hogql" if use_native_schema else "clickhouse"
            ),
        )
        if use_native_schema:
            resolve_types(clone_expr(parsed_query, clear_types=True), context=context, dialect="clickhouse")
    except ExposedHogQLError as e:
        raise UnsupportedHogQLQueryError(f"Invalid HogQL query: {e}")

    return prepared_select_query


class _DatabaseFieldFinder(TraversingVisitor):
    """Walk an AST subtree and collect the names of the database fields it reads."""

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.names: set[str] = set()

    def visit_field(self, node: ast.Field):
        resolve = getattr(node.type, "resolve_database_field", None)
        if resolve is not None:
            database_field = resolve(self.context)
            name = getattr(database_field, "name", None)
            if name is not None:
                self.names.add(name)
        super().visit_field(node)


def _check_events_hogql_query(team_id: int, user: "User | None", hogql_query: str) -> ast.SelectQuery:
    """Validate a HogQL query being used for events batch exports.

    This function checks that a query is supported by batch exports:
    1. UNION ALL is not supported.
    2. Any JOINs are not supported.
    3. Query must SELECT FROM events, and only from events.
    4. Subqueries in SELECT expressions are not supported.
    5. Query must select only from those fields we expose from the events table.
    """
    parsed = parse_events_hogql_query(hogql_query, team_id=team_id, user=user)

    if isinstance(parsed, ast.SelectSetQuery):
        raise UnsupportedHogQLQueryError("UNIONs are not supported")

    parsed = typing.cast(ast.SelectQuery, parsed)

    if parsed.select_from is None:
        raise UnsupportedHogQLQueryError("Query must SELECT FROM events")

    if parsed.ctes:
        raise UnsupportedHogQLQueryError("CTEs are not supported")

    if isinstance(parsed.select_from.table, (ast.SelectQuery, ast.SelectSetQuery)):
        raise UnsupportedHogQLQueryError("Subqueries are not supported")

    # Not sure how to make mypy understand this works, hence the ignore comment.
    # And if it doesn't, it's still okay as it could mean an unsupported query.
    # We would come back with the example to properly type this.
    if parsed.select_from.table.chain != ["events"]:  # type: ignore
        raise UnsupportedHogQLQueryError("Query must only SELECT FROM events")

    if parsed.select_from.next_join is not None:
        raise UnsupportedHogQLQueryError("JOINs are not supported")

    if any(contains_subquery(field) for field in parsed.select):
        raise UnsupportedHogQLQueryError("Subqueries in SELECT expressions are not supported")

    # Check that the query only selects from those fields we expose from the events table.
    field_finder = _DatabaseFieldFinder(HogQLContext(team_id=team_id, enable_select_queries=True))
    for field in parsed.select:
        field_finder.visit(field)

    unsupported = sorted(field_finder.names - EXPORTABLE_EVENTS_MODEL_FIELDS)
    if unsupported:
        raise UnsupportedHogQLQueryError(
            f"Batch exports cannot read these fields: {', '.join(unsupported)}. "
            f"Supported fields are: {', '.join(sorted(EXPORTABLE_EVENTS_MODEL_FIELDS))}."
        )

    return parsed


def serialize_events_query_schema(
    team_id: int, user: "User | None", hogql_query: ast.SelectQuery
) -> "BatchExportSchema":
    """Return a batch export schema from a HogQL query ast."""
    from products.access_control.backend.facade.api import (  # noqa: PLC0415 — keeps Django access-control imports off the batch worker import path
        get_restricted_properties_with_group_type_index_for_team,
    )

    restricted_properties = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    context = HogQLContext(
        team_id=team_id,
        user=user,
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=restricted_properties,
        modifiers=HogQLQueryModifiers(
            personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        ),
    )
    if context.uses_new_events_schema():
        context.modifiers.materializationMode = MaterializationMode.DISABLED
    try:
        schema = serialize_batch_export_query(hogql_query, context)
    except ExposedHogQLError:
        raise UnsupportedHogQLQueryError("Unsupported HogQL query")
    if context.restricted_properties:
        schema.pop("hogql_query", None)
    return schema


def build_events_query_schema(team_id: int, user: "User | None", hogql_query: str) -> "BatchExportSchema":
    """Check a legacy events model query, and return the schema an export stores for it."""
    return serialize_events_query_schema(team_id, user, _check_events_hogql_query(team_id, user, hogql_query))
