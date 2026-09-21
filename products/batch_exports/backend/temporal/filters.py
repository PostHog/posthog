"""Composing HogQL property filters into ClickHouse clauses for batch exports.

Batch exports let users filter which events are exported. The filters arrive as serialized
HogQL, and this turns them into a printed ClickHouse boolean clause plus the placeholder values
to send alongside it.
"""

import typing

from posthog.schema import EventPropertyFilter, HogQLPropertyFilter, HogQLQueryModifiers, MaterializationMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError
from posthog.hogql.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import Team

from products.batch_exports.backend.service import SUPPORTED_FILTER_TYPES


class UpdatePropertiesToPersonProperties(TraversingVisitor):
    """Update 'properties' to 'events.poe.properties' in all fields."""

    def visit_field(self, node: ast.Field):
        if node.chain and node.chain[0] == "properties":
            node.chain = ["events", "poe", "properties", *node.chain[1:]]


class InvalidFilterError(Exception):
    """Error raised when an invalid filter is used."""

    def __init__(self, error: ExposedHogQLError | InternalHogQLError):
        if isinstance(error, ExposedHogQLError):
            msg = f"One or more provided filters are invalid: {error}"
        else:
            # TODO: Figure out if we can include some debug information from internal
            # errors too
            msg = "One or more provided filters are invalid"
        super().__init__(msg)


def compose_filters_clause(
    filters: list[dict[str, str | list[str] | None]],
    team_id: int,
    values: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Compose a clause of matching filters for a batch exports query.

    `values` must be set if already replacing other values as otherwise there will
    be collisions with the values returned by this function.

    Arguments:
        filters: A list of serialized HogQL filters.
        team_id: Team we are running for.
        values: HogQL placeholder values already in use.

    Returns:
        A printed string with the ClickHouse SQL clause, and a dictionary
        of placeholder to values to be used as query parameters.
    """
    team = Team.objects.get(id=team_id)
    context = HogQLContext(
        team=team,
        team_id=team.id,
        enable_select_queries=False,
        limit_top_select=False,
        within_non_hogql_query=False,
        # Export SQL reads the legacy String-properties tables/views (events, events_recent,
        # events_batch_export), so filter fragments must stay on the legacy schema. Remove this pin
        # only together with porting those views and field lists to events_json.
        use_new_events_schema=False,
        values=values or {},
        modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
    )
    # Export models are only events/persons/sessions; warehouse tables and views are denied.
    # Pass bypass_warehouse_access_control=True or a user if that becomes an issue.
    context.database = Database.create_for(team=team, modifiers=context.modifiers)
    exprs = []
    for filter in filters:
        filter_type = filter["type"]
        if filter_type not in SUPPORTED_FILTER_TYPES:
            raise TypeError(f"Unknown filter type: '{filter_type}'")

        match filter_type:
            case "event":
                exprs.append(property_to_expr(EventPropertyFilter(**filter), team=team))
            case "person":
                # HACK: We are trying to apply the filter to 'events.person_properties' as that would
                # mimic workflows behavior of applying it to the person in the event but:
                # 1. PersonPropertyFilter expects a join with the person table, so we can't use it.
                # 2. 'persons_properties' doesn't exist in the HogQL 'EventsTable', so we can't use it.
                # So, we treat this filter like an events property filter (for 1) and manually update
                # the chain to point to 'events.poe.properties' which does exist in 'EventsTable' (for 2).
                # This will get resolved to 'events.person_properties' in ClickHouse dialect. This is done
                # using a visitor, which makes it slightly less of a hack.
                # I attempted to add a new property filter just for us to use here, but it was a mess
                # requiring multiple unnecessary (for us) file changes, and consistently failed type checks
                # everywhere in hogql modules.
                expr = property_to_expr(EventPropertyFilter(**{**filter, **{"type": "event"}}), team=team)
                UpdatePropertiesToPersonProperties().visit(expr)
                exprs.append(expr)

            case "hogql":
                try:
                    exprs.append(property_to_expr(HogQLPropertyFilter(**filter), team=team))
                except (ExposedHogQLError, InternalHogQLError) as e:
                    raise InvalidFilterError(e) from e

            case _:
                # Reachable only if SUPPORTED_FILTER_TYPES gains a type without a handler here.
                raise TypeError(f"Unhandled filter type: '{filter_type}'")

    and_expr = ast.And(exprs=exprs)
    # This query only supports events at the moment.
    # TODO: Extend for other models that also wish to implement property filtering.
    select_query = ast.SelectQuery(
        select=[
            parse_expr("properties as properties"),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=and_expr,
    )
    prepared_select_query: ast.SelectQuery = typing.cast(
        ast.SelectQuery, prepare_ast_for_printing(select_query, context=context, dialect="hogql", stack=[select_query])
    )
    prepared_and_expr = prepare_ast_for_printing(
        and_expr, context=context, dialect="clickhouse", stack=[prepared_select_query]
    )

    try:
        printed = print_prepared_ast(
            prepared_and_expr,  # type: ignore
            context=context,
            dialect="clickhouse",
            stack=[prepared_select_query],
        )
    except (ExposedHogQLError, InternalHogQLError) as e:
        raise InvalidFilterError(e) from e

    return printed, context.values
