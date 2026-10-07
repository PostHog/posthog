import re
from datetime import datetime, timedelta
from functools import cached_property
from itertools import batched
from typing import cast
from uuid import UUID

from django.utils.timezone import now

import orjson
import structlog

from posthog.schema import (
    AnyPropertyFilterDiscriminated,
    CachedEventsQueryResponse,
    DashboardFilter,
    EventPropertyFilter,
    EventsQuery,
    EventsQueryResponse,
    HogQLQueryModifiers,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.ast import Alias
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.flag_evaluations import (
    EVENTS_LIST_JOINED_FIELDS,
    add_events_list_fields_to_flag_evaluations,
)
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import (
    action_to_expr,
    has_aggregation,
    map_virtual_properties,
    property_to_expr,
    steps_to_expr,
)
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import TraversingVisitor

from posthog.api.element import ElementSerializer
from posthog.api.person import PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
from posthog.caching.utils import ThresholdMode, is_stale
from posthog.clickhouse.query_tagging import tag_contains_user_hogql
from posthog.dataclasses import frozen
from posthog.date_util import start_of_day
from posthog.hogql_queries.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.hogql_queries.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, get_query_runner
from posthog.hogql_queries.utils.person_display_name import person_display_name_property_exprs
from posthog.models import Person, PropertyDefinition
from posthog.models.element import chain_to_elements
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT, FLAG_EVALUATIONS_TTL_DAYS
from posthog.models.person.person import MAX_LIMIT_DISTINCT_IDS, get_distinct_ids_for_subquery
from posthog.models.person.util import get_person_by_pk_or_uuid, get_persons_mapped_by_distinct_id
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.utils import relative_date_parse, relative_date_parse_with_delta_mapping

from products.actions.backend.models.action import Action, ActionStepJSON
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_flag_evaluations_read_mode

logger = structlog.get_logger(__name__)

# Allow-listed fields returned when you select "*" from events. Person and group fields will be nested later.
SELECT_STAR_FROM_EVENTS_FIELDS = [
    "uuid",
    "event",
    "properties",
    "timestamp",
    "team_id",
    "distinct_id",
    "elements_chain",
    "created_at",
    "person_mode",
]

# Wide columns that defeat presorted optimization
WIDE_COLUMNS = {"elements_chain", "properties"}


@frozen
class EventsListTable:
    chain: tuple[str, ...]
    alias: str | None
    person_id: str
    looks_up_person_display_names: bool
    # Fields that join another table. The outer presorted query leaves out filters on them.
    joined_fields: frozenset[str]
    # The list starts no earlier than the UTC start of the day this many days back.
    retention_days: int | None
    cache_key_variant: str

    def join_expr(self) -> ast.JoinExpr:
        return ast.JoinExpr(table=ast.Field(chain=[*self.chain]), alias=self.alias)


EVENTS_LIST_TABLE = EventsListTable(
    chain=("events",),
    alias=None,
    person_id="person.id",
    looks_up_person_display_names=False,
    joined_fields=frozenset(),
    retention_days=None,
    cache_key_variant="",
)
FLAG_EVALUATIONS_LIST_TABLE = EventsListTable(
    chain=("posthog", "flag_evaluations"),
    # Resolver.visit_join_expr names an unaliased posthog.flag_evaluations "posthog__flag_evaluations".
    # LazyTableResolver looks for a join's source table by chain[0], which is "posthog". That lookup misses.
    # It then prints the persons join before the override join that the persons join condition reads.
    alias="flag_evaluations",
    # The persons join reads a zero UUID from person.id for a distinct_id with no person row.
    # person_id holds the id that flag_evaluations resolved through person merges.
    person_id="person_id",
    # Reading person.properties in the query joins persons. That join deduplicates every person in the team before
    # the query picks the page. The runner reads display names for only the page's persons after the query, unless
    # the query sorts by Person and joins persons anyway.
    looks_up_person_display_names=True,
    joined_fields=EVENTS_LIST_JOINED_FIELDS,
    # flag_evaluations drops a monthly part only after its newest row passes the TTL. Rows older than the TTL can
    # therefore remain for up to a month. This bound ends the list at the first day that the Usage tab charts show.
    # The TTL has already expired the rows of that day when today starts, so the list can show only part of that day.
    # The day is empty after a TTL merge drops every part that holds it.
    retention_days=FLAG_EVALUATIONS_TTL_DAYS,
    cache_key_variant="_flag_evaluations",
)


class _FieldUnderFinder(TraversingVisitor):
    def __init__(self, roots: frozenset[str]) -> None:
        super().__init__()
        self.roots = roots
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if node.chain and node.chain[0] in self.roots:
            self.found = True


def _reads_field_under(expr: ast.Expr, roots: frozenset[str]) -> bool:
    finder = _FieldUnderFinder(roots)
    finder.visit(expr)
    return finder.found


# Pagination cursors are encoded as ``<timestamp>|<uuid>`` so a stable uuid tiebreaker can advance
# past events that share the boundary timestamp instead of dropping every tied row beyond the page
# limit (which happens with a plain exclusive ``timestamp <`` filter). Coarse-precision sources such
# as bulk imports routinely land hundreds of events on the same second, so ties are not rare there.
CURSOR_DELIMITER = "|"


@frozen
class TimestampBoundary:
    plain: str
    with_uuid_tiebreaker: str


BEFORE_BOUNDARY = TimestampBoundary(
    plain="timestamp < {boundary}",
    with_uuid_tiebreaker="timestamp < {boundary} OR (timestamp = {boundary_eq} AND uuid < {boundary_uuid})",
)
AFTER_BOUNDARY = TimestampBoundary(
    plain="timestamp > {boundary}",
    with_uuid_tiebreaker="timestamp > {boundary} OR (timestamp = {boundary_eq} AND uuid > {boundary_uuid})",
)


def and_exprs(existing: ast.Expr | None, extra: ast.Expr | None) -> ast.Expr | None:
    if extra is None:
        return existing
    if existing is None:
        return extra
    return ast.And(exprs=[existing, extra])


QueryPropertyFilter = AnyPropertyFilterDiscriminated | PropertyGroupFilter | PropertyGroupFilterValue


def _exact_flag_keys(prop: QueryPropertyFilter) -> list[str] | None:
    if not (
        isinstance(prop, EventPropertyFilter)
        and prop.key == "$feature_flag"
        and prop.operator == PropertyOperator.EXACT
    ):
        return None
    values = prop.value if isinstance(prop.value, list) else [prop.value]
    if not values or not all(isinstance(value, str) for value in values):
        return None
    return [str(value) for value in values]


def _retention_start_expr(retention_days: int) -> ast.Expr:
    retention_start = start_of_day(now()) - timedelta(days=retention_days)
    return parse_expr("timestamp >= {retention_start}", {"retention_start": ast.Constant(value=retention_start)})


def split_pagination_cursor(value: str) -> tuple[str, str | None]:
    """Split a ``<timestamp>|<uuid>`` cursor. Plain user-supplied date filters have no delimiter and
    pass through unchanged with a ``None`` tiebreaker."""
    timestamp, delimiter, uuid = value.partition(CURSOR_DELIMITER)
    return timestamp, (uuid if delimiter else None)


class EventsQueryRunner(AnalyticsQueryRunner[EventsQueryResponse]):
    query: EventsQuery
    cached_response: CachedEventsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )
        self._cursor_eligible = False

    @cached_property
    def source_runner(self) -> InsightActorsQueryRunner:
        if not self.query.source:
            raise ValueError("Source query is required")

        return cast(
            InsightActorsQueryRunner,
            get_query_runner(
                self.query.source, self.team, self.timings, self.limit_context, self.modifiers, user=self.user
            ),
        )

    def validate(self) -> None:
        super().validate()
        if self.query.source is not None:
            self.source_runner.validate()

    def _person_display_name_key(self, table: EventsListTable) -> str:
        props = self._person_display_name_property_exprs("person.properties")
        return f"coalesce({', '.join([*props, 'distinct_id'])}), toString({table.person_id})"

    def _person_display_names_after_query(self, table: EventsListTable) -> bool:
        """Whether the page lookup fills person_display_name, rather than the page query.

        A sort by the Person column reads person.properties, which joins persons. The query then reads the names
        from that join, and the lookup does not run.
        """
        return table.looks_up_person_display_names and not self._sorts_by_person_display_name()

    def _sorts_by_person_display_name(self) -> bool:
        if self.query.orderBy is not None:
            return any(col.split("--")[0].strip() == "person_display_name" for col in self.query.orderBy)
        columns = self.select_input_raw()
        return columns[0].split("--")[0].strip() == "person_display_name" and self._default_order_is_first_column(
            columns, any(has_aggregation(parse_expr(column)) for column in columns)
        )

    def select_cols(self, table: EventsListTable) -> tuple[list[str], list[ast.Expr]]:
        select_input: list[str] = []
        person_indices: list[int] = []
        for index, col in enumerate(self.select_input_raw()):
            # Selecting a "*" expands the list of columns, resulting in a table that's not what we asked for.
            # Instead, ask for a tuple with all the columns we want. Later transform this back into a dict.
            if col == "*":
                select_input.append(f"tuple({', '.join(SELECT_STAR_FROM_EVENTS_FIELDS)})")
            elif col.split("--")[0].strip() == "person":
                # This will be expanded into a followup query
                select_input.append("distinct_id")
                person_indices.append(index)
            elif col.split("--")[0].strip() == "person_display_name":
                if self._person_display_names_after_query(table):
                    # _expand_person_display_name_columns replaces distinct_id with the person's name.
                    select_input.append(f"(distinct_id, toString({table.person_id}), distinct_id)")
                else:
                    select_input.append(f"({self._person_display_name_key(table)}, distinct_id)")
            else:
                select_input.append(col)
        return select_input, [
            map_virtual_properties(parse_expr(column, timings=self.timings)) for column in select_input
        ]

    def _can_use_presorted_optimization(self, order_by: list[ast.OrderExpr] | None) -> bool:
        """
        Check if ORDER BY can use presorted optimization.

        We can optimize any ORDER BY that doesn't need wide columns directly.
        - properties.$foo is fine (we extract just that value)
        - elements_chain or raw properties blob is not fine
        """
        if not order_by:
            return False

        for order_expr in order_by:
            if isinstance(order_expr.expr, ast.Field) and order_expr.expr.chain:
                first = order_expr.expr.chain[0]
                if first in WIDE_COLUMNS:
                    # properties.$foo is fine - we extract just that property
                    if first == "properties" and len(order_expr.expr.chain) >= 2:
                        continue
                    return False

        return True

    def apply_pagination_cursor(self, cursor: str) -> None:
        # The cursor is a ``<timestamp>|<uuid>`` pair (see ``split_pagination_cursor``); ``to_query``
        # turns it into a timestamp filter with a uuid tiebreaker so events sharing the boundary
        # timestamp are not skipped. Bare-timestamp cursors from older clients still work.
        order: str = "DESC"
        if self.query.orderBy:
            order = parse_order_expr(self.query.orderBy[0]).order
        if order == "ASC":
            self.query.after = cursor
        else:
            self.query.before = cursor

    def _extract_last_timestamp(self, row: list) -> str | None:
        select_input = self.select_input_raw()
        val = None
        if "*" in select_input:
            star_idx = select_input.index("*")
            if isinstance(row[star_idx], dict):
                val = row[star_idx].get("timestamp")
        if val is None:
            for i, col in enumerate(select_input):
                if col.split("--")[0].strip() == "timestamp":
                    val = row[i]
                    break
        if val is None:
            return None
        if isinstance(val, datetime):
            return val.isoformat()
        return str(val)

    def _extract_last_uuid(self, row: list) -> str | None:
        select_input = self.select_input_raw()
        if "*" in select_input:
            star_idx = select_input.index("*")
            if isinstance(row[star_idx], dict) and row[star_idx].get("uuid") is not None:
                return str(row[star_idx]["uuid"])
        for i, col in enumerate(select_input):
            if col.split("--")[0].strip() == "uuid" and row[i] is not None:
                return str(row[i])
        return None

    def _raise_on_restricted_property_select(self) -> None:
        # User-authored ``select`` entries that explicitly reference a restricted event or person
        # property must fail loudly — the printer's silent JSONDropKeys strip would otherwise turn
        # the request into an empty string, which is surprising when the field name was typed by hand.
        #
        # Check the raw user columns, not the expanded select list. PostHog's own pseudo-columns
        # (``person``, ``person_display_name``) expand to expressions that reference restricted
        # person properties such as ``email``; those values are masked elsewhere, so walking the
        # expansion here would wrongly fail the whole query instead of degrading gracefully.
        from posthog.hogql.errors import ResolutionError
        from posthog.hogql.visitor import TraversingVisitor

        from products.access_control.backend.property_access_control import get_restricted_property_names

        restricted_event_props = get_restricted_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.EVENT,
        )
        restricted_person_props = get_restricted_property_names(
            team_id=self.team.pk,
            user=self.user,
            property_type=PropertyDefinition.Type.PERSON,
        )
        if not restricted_event_props and not restricted_person_props:
            return

        class _Checker(TraversingVisitor):
            def visit_field(self, node: ast.Field) -> None:
                chain = [str(c) for c in node.chain]
                # ``properties.<name>`` on the events table.
                if len(chain) >= 2 and chain[0] == "properties" and chain[1] in restricted_event_props:
                    raise ResolutionError(f"Access to property '{chain[1]}' is restricted")
                # ``person.properties.<name>`` (or ``poe.properties.<name>``) on the joined person.
                if (
                    len(chain) >= 3
                    and chain[0] in ("person", "poe")
                    and chain[1] == "properties"
                    and chain[2] in restricted_person_props
                ):
                    raise ResolutionError(f"Access to property '{chain[2]}' is restricted")

        checker = _Checker()
        for col in self.select_input_raw():
            stripped = col.split("--")[0].strip()
            # Skip PostHog-generated pseudo-columns; their expansion is masked, not restricted.
            if col == "*" or stripped in ("person", "person_display_name"):
                continue
            checker.visit(map_virtual_properties(parse_expr(col, timings=self.timings)))

    def to_query(self) -> ast.SelectQuery:
        return self._build_query(EVENTS_LIST_TABLE)

    def _build_query(self, table: EventsListTable) -> ast.SelectQuery:
        # Note: This code is inefficient and problematic, see https://github.com/PostHog/posthog/issues/13485 for details.
        with self.timings.measure("build_ast"):
            # columns & group_by
            with self.timings.measure("columns"):
                select_input, select = self.select_cols(table)
                self._raise_on_restricted_property_select()

            with self.timings.measure("aggregations"):
                group_by: list[ast.Expr] = [column for column in select if not has_aggregation(column)]
                aggregations: list[ast.Expr] = [column for column in select if has_aggregation(column)]
                has_any_aggregation = len(aggregations) > 0

            where_exprs = self._filter_where_exprs(table)
            where_exprs.extend(self._timestamp_where_exprs(table))

            # where & having
            with self.timings.measure("where"):
                where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
                where: ast.Expr | None = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having: ast.Expr | None = ast.And(exprs=having_list) if len(having_list) > 0 else None

            order_by = self._order_by_exprs(table, select_input, select, aggregations, has_any_aggregation)

            with self.timings.measure("select"):
                if self.query.source is not None:
                    return self._source_events_query(select, where, having, group_by, order_by, has_any_aggregation)
                return self._events_query(table, select, where, having, group_by, order_by, has_any_aggregation)

    def _event_names(self) -> list[str]:
        return [e for e in [self.query.event, *(self.query.events or [])] if e]

    @cached_property
    def _list_table(self) -> EventsListTable:
        if self.query.source is not None or self.query.actionId or self.query.actionSteps:
            return EVENTS_LIST_TABLE
        if set(self._event_names()) != {FLAG_EVALUATIONS_SOURCE_EVENT}:
            return EVENTS_LIST_TABLE
        if get_flag_evaluations_read_mode(self.team.organization_id) == FlagEvaluationsMode.EVENTS:
            return EVENTS_LIST_TABLE
        return FLAG_EVALUATIONS_LIST_TABLE

    def get_cache_key_variant(self) -> str:
        return super().get_cache_key_variant() + self._list_table.cache_key_variant

    def _property_where_expr(self, prop: QueryPropertyFilter, table: EventsListTable) -> ast.Expr:
        flag_keys = _exact_flag_keys(prop) if table is FLAG_EVALUATIONS_LIST_TABLE else None
        if flag_keys is None:
            return property_to_expr(prop, self.team)
        # HogQL reads properties.$feature_flag from the properties JSON, which reads the properties of every call of
        # the flag in the date range. flag_key holds the same value and leads the table's sort key after team_id.
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["flag_key"]),
            right=ast.Tuple(exprs=[ast.Constant(value=key) for key in flag_keys]),
        )

    def _query_modifiers(self, table: EventsListTable) -> HogQLQueryModifiers:
        # flag_evaluations rows carry no person properties, so a person filter joins persons.
        # The pushdown limits that join to the persons that the page's flag calls reach.
        # An explicit personIdPushdown value on the team or the query still wins.
        if table is FLAG_EVALUATIONS_LIST_TABLE and self.modifiers.personIdPushdown is None:
            return self.modifiers.model_copy(update={"personIdPushdown": True})
        return self.modifiers

    def _query_context(self, table: EventsListTable) -> HogQLContext:
        context = self.build_hogql_context()
        assert context.database is not None
        if table is FLAG_EVALUATIONS_LIST_TABLE:
            add_events_list_fields_to_flag_evaluations(context.database)
        return context

    def _filter_where_exprs(self, table: EventsListTable) -> list[ast.Expr]:
        with self.timings.measure("filters"):
            with self.timings.measure("where"):
                where_input = self.query.where or []
                where_exprs = [parse_expr(expr, timings=self.timings) for expr in where_input]
            if self.query.properties:
                with self.timings.measure("properties"):
                    where_exprs.extend(self._property_where_expr(prop, table) for prop in self.query.properties)
            if self.query.fixedProperties:
                with self.timings.measure("fixed_properties"):
                    where_exprs.extend(self._property_where_expr(prop, table) for prop in self.query.fixedProperties)
            all_events = self._event_names()
            if all_events:
                with self.timings.measure("event"):
                    where_exprs.append(self._event_where_expr(all_events))
            if self.query.actionId:
                with self.timings.measure("action_id"):
                    where_exprs.append(self._action_where_expr(self.query.actionId))
            elif self.query.actionSteps:
                with self.timings.measure("action_steps"):
                    where_exprs.append(self._action_steps_where_expr())
            if self.query.personId:
                with self.timings.measure("person_id"), personhog_caller_tag("persons/events-query"):
                    where_exprs.append(self._person_where_expr(self.query.personId))
            if self.query.filterTestAccounts:
                with self.timings.measure("test_account_filters"):
                    where_exprs.extend(
                        property_to_expr(prop, self.team) for prop in self.team.test_account_filters or []
                    )
            return where_exprs

    def _event_where_expr(self, all_events: list[str]) -> ast.Expr:
        if len(all_events) == 1:
            return parse_expr(
                "event = {event}",
                {"event": ast.Constant(value=all_events[0])},
                timings=self.timings,
            )
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["event"]),
            right=ast.Tuple(exprs=[ast.Constant(value=e) for e in all_events]),
        )

    def _action_where_expr(self, action_id: int) -> ast.Expr:
        try:
            action = Action.objects.get(pk=action_id, team__project_id=self.team.project_id)
        except Action.DoesNotExist:
            raise Exception("Action does not exist")
        if not action.steps:
            raise Exception("Action does not have any match groups")
        return action_to_expr(action)

    def _action_steps_where_expr(self) -> ast.Expr:
        steps = [
            ActionStepJSON(
                event=s.event,
                tag_name=s.tag_name,
                text=s.text,
                text_matching=s.text_matching.value if s.text_matching else None,
                href=s.href,
                href_matching=s.href_matching.value if s.href_matching else None,
                selector=s.selector,
                url=s.url,
                url_matching=s.url_matching.value if s.url_matching else None,
                properties=[p.model_dump() for p in s.properties] if s.properties else None,
            )
            for s in self.query.actionSteps or []
        ]
        return steps_to_expr(steps, self.team)

    def _person_where_expr(self, person_id: str) -> ast.Expr:
        person: Person | None = get_person_by_pk_or_uuid(
            self.team.pk, person_id, distinct_id_limit=MAX_LIMIT_DISTINCT_IDS
        )
        return ast.CompareOperation(
            left=ast.Call(name="cityHash64", args=[ast.Field(chain=["distinct_id"])]),
            right=ast.Tuple(
                exprs=[
                    ast.Call(name="cityHash64", args=[ast.Constant(value=id)])
                    for id in get_distinct_ids_for_subquery(person, self.team)
                ]
            ),
            op=ast.CompareOperationOp.In,
        )

    def _timestamp_where_exprs(self, table: EventsListTable) -> list[ast.Expr]:
        with self.timings.measure("timestamps"):
            # prevent accidentally future events from being visible by default
            before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
            exprs = [self._timestamp_boundary_expr(before, BEFORE_BOUNDARY)]

            # limit to the last 24h by default
            after = self.query.after or "-24h"
            if after != "all":
                exprs.append(self._timestamp_boundary_expr(after, AFTER_BOUNDARY))
            if table.retention_days is not None:
                exprs.append(_retention_start_expr(table.retention_days))
            return exprs

    def _timestamp_boundary_expr(self, cursor: str, boundary: TimestampBoundary) -> ast.Expr:
        timestamp, cursor_uuid = split_pagination_cursor(cursor)
        parsed_date = relative_date_parse(timestamp, self.team.timezone_info)
        if cursor_uuid is None:
            return parse_expr(
                boundary.plain,
                {"boundary": ast.Constant(value=parsed_date)},
                timings=self.timings,
            )
        # Advance past events sharing the boundary timestamp using uuid as a tiebreaker,
        # matching the ``timestamp DESC, uuid DESC`` ordering that `_order_by_exprs` applies.
        return parse_expr(
            boundary.with_uuid_tiebreaker,
            {
                "boundary": ast.Constant(value=parsed_date),
                "boundary_eq": ast.Constant(value=parsed_date),
                "boundary_uuid": ast.Call(name="toUUID", args=[ast.Constant(value=cursor_uuid)]),
            },
            timings=self.timings,
        )

    def _pinned_boundary(self, boundary: str) -> datetime | None:
        timestamp = split_pagination_cursor(boundary)[0]
        parsed, delta_mapping, _ = relative_date_parse_with_delta_mapping(timestamp, self.team.timezone_info)
        return parsed if delta_mapping is None else None

    @cached_property
    def _pinned_date_to(self) -> datetime | None:
        """The end of the queried window, but only when both ends of it are pinned to fixed instants.

        `None` means an end moves with the clock, so the window a cached result covers has already
        slid past and every event since that calculation is missing from it.
        """
        before, after = self.query.before, self.query.after
        if before is None or after is None:
            return None
        date_to = self._pinned_boundary(before)
        if date_to is None:
            return None
        if after != "all" and self._pinned_boundary(after) is None:
            return None
        return date_to

    def _is_stale(self, last_refresh: datetime | None, lazy: bool = False) -> bool:
        date_to = self._pinned_date_to
        if date_to is None:
            return True
        mode = ThresholdMode.LAZY if lazy else ThresholdMode.DEFAULT
        return is_stale(self.team, date_to=date_to, interval=None, last_refresh=last_refresh, mode=mode)

    def cache_target_age(self, last_refresh: datetime | None, lazy: bool = False) -> datetime | None:
        if last_refresh is not None and self._pinned_date_to is None:
            return last_refresh
        return super().cache_target_age(last_refresh, lazy=lazy)

    def _order_by_exprs(
        self,
        table: EventsListTable,
        select_input: list[str],
        select: list[ast.Expr],
        aggregations: list[ast.Expr],
        has_any_aggregation: bool,
    ) -> list[ast.OrderExpr]:
        with self.timings.measure("order"):
            if self.query.orderBy is not None:
                order_by = self._requested_order_by(table, self.query.orderBy)
            else:
                order_by = self._default_order_by(select_input, select, aggregations)

            first_order = order_by[0].expr if order_by else None
            self._cursor_eligible = (
                self.query.source is None
                and not has_any_aggregation
                and isinstance(first_order, ast.Field)
                and first_order.chain == ["timestamp"]
            )

            # When ordering by timestamp, append uuid as a stable secondary sort so the ordering
            # is total. Ties on timestamp would otherwise be arbitrary and shift between pages,
            # which is what lets cursor pagination silently skip events sharing a timestamp.
            if self._cursor_eligible and not any(
                isinstance(o.expr, ast.Field) and o.expr.chain == ["uuid"] for o in order_by
            ):
                order_by.append(ast.OrderExpr(expr=ast.Field(chain=["uuid"]), order=order_by[0].order))
            return order_by

    def _requested_order_by(self, table: EventsListTable, order_by_input: list[str]) -> list[ast.OrderExpr]:
        columns: list[str] = []
        for col in order_by_input:
            if col.split("--")[0].strip() == "person_display_name":
                expr = f"({self._person_display_name_key(table)})"
                columns.append(re.sub(r"person_display_name -- Person ", expr, col))
            else:
                columns.append(col)
        return [parse_order_expr(column, timings=self.timings) for column in columns]

    @staticmethod
    def _default_order_is_first_column(select_input: list[str], has_any_aggregation: bool) -> bool:
        return "count()" not in select_input and not has_any_aggregation and "timestamp" not in select_input

    def _default_order_by(
        self, select_input: list[str], select: list[ast.Expr], aggregations: list[ast.Expr]
    ) -> list[ast.OrderExpr]:
        if self._default_order_is_first_column(select_input, len(aggregations) > 0):
            return [ast.OrderExpr(expr=select[0], order="ASC")] if select else []
        if "count()" in select_input:
            return [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
        if len(aggregations) > 0:
            return [ast.OrderExpr(expr=aggregations[0], order="DESC")]
        return [ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")]

    def _source_events_query(
        self,
        select: list[ast.Expr],
        where: ast.Expr | None,
        having: ast.Expr | None,
        group_by: list[ast.Expr],
        order_by: list[ast.OrderExpr],
        has_any_aggregation: bool,
    ) -> ast.SelectQuery:
        # Kludge: If the events_query has logic in select that the where clauses depends on, this will potentially error.
        # If we implement that for other runners, make this smarter.
        events_query = self.source_runner.to_events_query()
        events_query.select = select
        events_query.where = and_exprs(events_query.where, where)
        events_query.having = and_exprs(events_query.having, having)
        events_query.group_by = group_by if has_any_aggregation else None
        events_query.order_by = order_by
        return events_query

    def _events_query(
        self,
        table: EventsListTable,
        select: list[ast.Expr],
        where: ast.Expr | None,
        having: ast.Expr | None,
        group_by: list[ast.Expr],
        order_by: list[ast.OrderExpr],
        has_any_aggregation: bool,
    ) -> ast.SelectQuery:
        stmt = ast.SelectQuery(
            select=select,
            select_from=table.join_expr(),
            where=where,
            having=having,
            group_by=group_by if has_any_aggregation else None,
            order_by=order_by,
        )

        # Presorted optimization: sort narrow data (uuid) first, then fetch wide data for matched rows.
        # Avoids sorting giant rows with properties and elements_chain cols - instead sorts uuids.
        if self._can_use_presorted_optimization(order_by) and not has_any_aggregation:
            logger.info(
                "events_query_runner_presorted_optimization",
                team_id=self.team.pk,
            )
            stmt.where = self._presorted_where(table, where, order_by)

        return stmt

    def _presorted_where(
        self, table: EventsListTable, where: ast.Expr | None, order_by: list[ast.OrderExpr]
    ) -> ast.Expr:
        inner_query = ast.SelectQuery(
            select=[ast.Field(chain=["uuid"])],
            select_from=table.join_expr(),
            where=where,
            order_by=order_by,
            limit=ast.Constant(value=self.paginator.limit + self.paginator.offset + 1),
        )

        prefilter_sorted = parse_expr("uuid in ({inner_query})", {"inner_query": inner_query})
        outer_where = self._presorted_outer_where(table, where)
        return ast.And(exprs=[prefilter_sorted, outer_where]) if outer_where is not None else prefilter_sorted

    @staticmethod
    def _presorted_outer_where(table: EventsListTable, where: ast.Expr | None) -> ast.Expr | None:
        # The inner query applies every filter. The outer query keeps a filter only to narrow its own scan.
        # A filter that reads a joined field would join that table a second time.
        if where is None or not table.joined_fields:
            return where
        exprs = where.exprs if isinstance(where, ast.And) else [where]
        kept = [expr for expr in exprs if not _reads_field_under(expr, table.joined_fields)]
        return ast.And(exprs=kept) if kept else None

    def _calculate(self) -> EventsQueryResponse:
        # Tag here (not in `to_query()`) so platform code that calls `to_query()` as a
        # sub-query helper — e.g. `hogql_cohort_query.py` — doesn't false-positive when
        # the `select` / `where` strings it builds are platform constants. User-facing
        # `EventsQuery` execution always lands in `_calculate()` via the runner.
        tag_contains_user_hogql()
        # Only this path reads flag_evaluations. Callers that run to_query() in their own context keep reading
        # events. Their select or database may need columns that flag_evaluations lacks.
        table = self._list_table
        modifiers = self._query_modifiers(table)
        query_result = self.paginator.execute_hogql_query(
            query=self._build_query(table),
            team=self.team,
            query_type="EventsQuery",
            timings=self.timings,
            modifiers=modifiers,
            limit_context=self.limit_context,
            user=self.user,
            context=self._query_context(table),
        )

        if "*" in self.select_input_raw():
            self._expand_star_column()
            if len(self.paginator.results) > 0:
                self._annotate_session_recordings()

        person_indices = self._expand_person_display_name_columns(table)

        # TODO: get rid of this logic once we don't use `person` columns anywhere
        if len(person_indices) > 0 and len(self.paginator.results) > 0:
            self._expand_person_columns(person_indices)

        return EventsQueryResponse(
            results=self.paginator.results,
            columns=self.columns(query_result.columns),
            types=[t for _, t in query_result.types] if query_result.types else [],
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
            modifiers=modifiers,
            nextCursor=self._next_cursor(),
            **self.paginator.response_params(),
        )

    def _expand_star_column(self) -> None:
        """Convert the star field from a tuple to a dict in each result."""
        with self.timings.measure("expand_asterisk"):
            star_idx = self.select_input_raw().index("*")
            for index, result in enumerate(self.paginator.results):
                self.paginator.results[index] = list(result)
                select = result[star_idx]
                new_result = dict(zip(SELECT_STAR_FROM_EVENTS_FIELDS, select))
                new_result["properties"] = orjson.loads(new_result["properties"])
                if new_result["elements_chain"]:
                    new_result["elements"] = ElementSerializer(
                        chain_to_elements(new_result["elements_chain"]), many=True
                    ).data
                self.paginator.results[index][star_idx] = new_result

    def _annotate_session_recordings(self) -> None:
        """Batch check which session IDs have recordings."""
        with self.timings.measure("session_recordings_check"):
            session_recordings_map = self.batch_check_session_recordings()
            star_idx = self.select_input_raw().index("*")
            for result in self.paginator.results:
                if not isinstance(result[star_idx], dict):
                    continue
                properties = result[star_idx].get("properties", {})
                if not isinstance(properties, dict):
                    continue
                session_id = properties.get("$session_id")
                if isinstance(session_id, str) and session_id:
                    properties["$has_recording"] = session_id in session_recordings_map

    def _expand_person_display_name_columns(self, table: EventsListTable) -> list[int]:
        """Convert each person_display_name tuple into a dict, and return the `person` column indices.

        When the page lookup fills the names, this queries `persons` in ClickHouse for the page's person ids.
        """
        person_indices: list[int] = []
        display_name_indices: list[int] = []
        for column_index, col in enumerate(self.select_input_raw()):
            stripped = col.split("--")[0].strip()
            if stripped == "person":
                person_indices.append(column_index)
            if stripped == "person_display_name":
                display_name_indices.append(column_index)

        names: dict[str, str] = {}
        if display_name_indices and self._person_display_names_after_query(table):
            with self.timings.measure("person_display_name_lookup"):
                names = self._person_display_names(
                    {
                        str(row[column_index][1])
                        for row in self.paginator.results
                        for column_index in display_name_indices
                    }
                )

        for column_index in display_name_indices:
            for index, result in enumerate(self.paginator.results):
                row = list(self.paginator.results[index])
                person_id = str(result[column_index][1])
                row[column_index] = {
                    "display_name": names.get(person_id, result[column_index][0]),
                    "id": person_id,
                    "distinct_id": str(result[column_index][2]),
                }
                self.paginator.results[index] = row
        return person_indices

    def _person_display_name_property_exprs(self, prefix: str) -> list[str]:
        property_keys = self.team.person_display_name_properties or PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES
        return person_display_name_property_exprs(property_keys, prefix)

    def _person_display_names(self, person_ids: set[str]) -> dict[str, str]:
        """Read display names from ClickHouse for only the given persons, keyed by person id."""
        name_exprs = [parse_expr(expr) for expr in self._person_display_name_property_exprs("properties")]
        names: dict[str, str] = {}
        # Sorting keeps the printed query the same for the same page.
        for batch in batched(sorted(person_ids), 1000, strict=False):
            # persons applies this id filter before it deduplicates person versions only when persons is the
            # query's own unaliased FROM. Under a join or an alias it deduplicates every person in the team first.
            query = ast.SelectQuery(
                select=[ast.Field(chain=["id"]), ast.Call(name="coalesce", args=name_exprs)],
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["id"]),
                    right=ast.Tuple(exprs=[ast.Constant(value=UUID(person_id)) for person_id in batch]),
                ),
                # Without a LIMIT, execute_hogql_query returns at most its default row count.
                limit=ast.Constant(value=len(batch)),
            )
            response = execute_hogql_query(
                query=query,
                team=self.team,
                user=self.user,
                query_type="EventsQueryPersonDisplayNames",
                timings=self.timings,
                modifiers=self.modifiers,
                context=self.build_hogql_context(),
            )
            names.update((str(person_id), name) for person_id, name in response.results if name)
        return names

    def _expand_person_columns(self, person_indices: list[int]) -> None:
        with self.timings.measure("person_column_extra_query"):
            distinct_to_person = self._persons_by_distinct_id(person_indices[0])

            # Load restricted person properties to strip from the side-channel result
            from products.access_control.backend.property_access_control import (
                get_restricted_property_names,
                strip_restricted_properties,
            )

            restricted_person_props = get_restricted_property_names(
                team_id=self.team.pk,
                user=self.user,
                property_type=PropertyDefinition.Type.PERSON,
            )

            # Loop over all columns in case there is more than one "person" column
            for column_index in person_indices:
                for index, result in enumerate(self.paginator.results):
                    distinct_id: str = result[column_index]
                    self.paginator.results[index] = list(result)
                    person = distinct_to_person.get(distinct_id)
                    if person is None:
                        self.paginator.results[index][column_index] = {"distinct_id": distinct_id}
                        continue
                    self.paginator.results[index][column_index] = {
                        "uuid": person.uuid,
                        "created_at": person.created_at,
                        "properties": strip_restricted_properties(person.properties or {}, restricted_person_props),
                        "distinct_id": distinct_id,
                    }

    def _persons_by_distinct_id(self, person_idx: int) -> dict[str, Person]:
        """Make a query into postgres to fetch the persons behind the `person` column."""
        distinct_ids = list({event[person_idx] for event in self.paginator.results})

        distinct_to_person: dict[str, Person] = {}
        batch_size = 1000
        with personhog_caller_tag("persons/events-person-column"):
            for i in range(0, len(distinct_ids), batch_size):
                batch_distinct_ids = distinct_ids[i : i + batch_size]
                distinct_to_person.update(get_persons_mapped_by_distinct_id(self.team.pk, batch_distinct_ids))
        return distinct_to_person

    def _next_cursor(self) -> str | None:
        if not (self._cursor_eligible and self.paginator.has_more() and self.paginator.results):
            return None
        last_row = self.paginator.results[-1]
        last_timestamp = self._extract_last_timestamp(last_row)
        if last_timestamp is None:
            return None
        last_uuid = self._extract_last_uuid(last_row)
        return f"{last_timestamp}{CURSOR_DELIMITER}{last_uuid}" if last_uuid else last_timestamp

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        if dashboard_filter.date_to or dashboard_filter.date_from:
            self.query.before = dashboard_filter.date_to
            self.query.after = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.properties = (self.query.properties or []) + dashboard_filter.properties

    def columns(self, result_columns: list | None) -> list[str]:
        _, select = self.select_cols(EVENTS_LIST_TABLE)
        columns = result_columns or []
        return [
            columns[idx] if len(columns) > idx and isinstance(select[idx], Alias) else col
            for idx, col in enumerate(self.select_input_raw())
        ]

    def select_input_raw(self) -> list[str]:
        return ["*"] if len(self.query.select) == 0 else self.query.select

    def batch_check_session_recordings(self) -> set[str]:
        """
        Batch check which session IDs have recordings.
        Returns a set of session IDs that have recordings.
        """
        # Extract all unique session IDs from events
        session_ids = set()
        star_idx = self.select_input_raw().index("*") if "*" in self.select_input_raw() else None

        for result in self.paginator.results:
            if star_idx is not None and isinstance(result[star_idx], dict):
                properties = result[star_idx].get("properties", {})
                if isinstance(properties, dict):
                    session_id = properties.get("$session_id")
                    if isinstance(session_id, str) and session_id:
                        session_ids.add(session_id)

        # If no session IDs, return empty set
        if not session_ids:
            return set()

        # Query to check which session IDs exist in raw_session_replay_events
        # Use the date range from the query to optimize the search
        after = self.query.after or "-24h"
        before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
        # before/after may carry a `<timestamp>|<uuid>` pagination cursor — only the timestamp matters here.
        after_timestamp = split_pagination_cursor(after)[0]
        before_timestamp = split_pagination_cursor(before)[0]
        date_from = relative_date_parse(after_timestamp, self.team.timezone_info) if after != "all" else None
        date_to = relative_date_parse(before_timestamp, self.team.timezone_info)

        where_conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["team_id"]),
                right=ast.Constant(value=self.team.pk),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["session_id"]),
                right=ast.Constant(value=list(session_ids)),
            ),
        ]

        # Sessions can start before events occur, so look back 1 day from date_from
        if date_from is not None:
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["min_first_timestamp"]),
                    right=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Sub,
                        left=ast.Constant(value=date_from),
                        right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)]),
                    ),
                )
            )

        where_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["min_first_timestamp"]),
                right=ast.Constant(value=date_to),
            )
        )

        session_check_query = ast.SelectQuery(
            select=[ast.Alias(alias="session_id", expr=ast.Field(chain=["session_id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_session_replay_events"])),
            where=ast.And(exprs=where_conditions),
            group_by=[ast.Field(chain=["session_id"])],
        )

        response = execute_hogql_query(
            query=session_check_query,
            team=self.team,
            user=self.user,
            query_type="EventsQuerySessionRecordingsCheck",
            timings=self.timings,
            modifiers=self.modifiers,
            context=self.build_hogql_context(),
        )

        # Return set of session IDs that exist
        return {row[0] for row in response.results if row}
