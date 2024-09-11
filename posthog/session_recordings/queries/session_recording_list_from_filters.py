from typing import Any, NamedTuple, cast, Optional, Union
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperation
from posthog.hogql.parser import parse_select
from posthog.hogql.property import entity_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team, Property
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyGroup
from posthog.schema import QueryTiming, HogQLQueryModifiers, PersonsOnEventsMode
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.constants import TREND_FILTER_TYPE_ACTIONS

import structlog

logger = structlog.get_logger(__name__)


def is_person_property(p: Property) -> bool:
    return p.type == "person" or (p.type == "hogql" and "person.properties" in p.key)


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool
    timings: list[QueryTiming] | None = None


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _team: Team
    _filter: SessionRecordingsFilter

    @staticmethod
    def _data_to_return(results: list[Any] | None) -> list[dict[str, Any]]:
        default_columns = [
            "session_id",
            "team_id",
            "distinct_id",
            "start_time",
            "end_time",
            "duration",
            "first_url",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "active_seconds",
            "inactive_seconds",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
        ]

        return [
            {
                **dict(zip(default_columns, row[: len(default_columns)])),
            }
            for row in results or []
        ]

    def __init__(
        self,
        team: Team,
        filter: SessionRecordingsFilter,
        hogql_query_modifiers: Optional[HogQLQueryModifiers],
        **_,
    ):
        self._team = team
        self._filter = filter
        self._paginator = HogQLHasMorePaginator(
            limit=filter.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT, offset=filter.offset or 0
        )
        self._hogql_query_modifiers = hogql_query_modifiers

    @property
    def ttl_days(self):
        return ttl_days(self._team)

    def run(self) -> SessionRecordingQueryResult:
        query = self.get_query()

        paginated_response = self._paginator.execute_hogql_query(
            # TODO I guess the paginator needs to know how to handle union queries or all callers are supposed to collapse them or .... 🤷
            query=cast(ast.SelectQuery, query),
            team=self._team,
            query_type="SessionRecordingListQuery",
            modifiers=self._hogql_query_modifiers,
        )

        return SessionRecordingQueryResult(
            results=(self._data_to_return(self._paginator.results)),
            has_more_recording=self._paginator.has_more(),
            timings=paginated_response.timings,
        )

    def get_query(self):
        return ast.SelectQuery(
            select=self._select(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_session_replay_events"]), alias="s"),
            where=self._where_predicates(),
            order_by=[self._order_by_clause()],
            group_by=[ast.Field(chain=["session_id"])],
            having=self._having_predicates(),
        )

    def _select(self) -> list[ast.Expr]:
        return [
            ast.Alias(alias="session_id", expr=ast.Field(chain=["s", "session_id"])),
            ast.Call(name="any", args=[ast.Field(chain=["s", "team_id"])]),
            ast.Call(name="any", args=[ast.Field(chain=["s", "distinct_id"])]),
            ast.Alias(
                alias="start_time",
                expr=ast.Call(name="min", args=[ast.Field(chain=["s", "min_first_timestamp"])]),
            ),
            ast.Alias(
                alias="end_time",
                expr=ast.Call(name="max", args=[ast.Field(chain=["s", "max_last_timestamp"])]),
            ),
            ast.Alias(
                alias="duration",
                expr=ast.Call(
                    name="dateDiff",
                    args=[ast.Constant(value="SECOND"), ast.Field(chain=["start_time"]), ast.Field(chain=["end_time"])],
                ),
            ),
            ast.Alias(
                alias="first_url",
                expr=ast.Call(name="argMinMerge", args=[ast.Field(chain=["s", "first_url"])]),
            ),
            ast.Alias(
                alias="click_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "click_count"])]),
            ),
            ast.Alias(
                alias="keypress_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "keypress_count"])]),
            ),
            ast.Alias(
                alias="mouse_activity_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "mouse_activity_count"])]),
            ),
            ast.Alias(
                alias="active_seconds",
                expr=ast.Call(
                    name="divide",
                    args=[
                        ast.Call(name="sum", args=[ast.Field(chain=["s", "active_milliseconds"])]),
                        ast.Constant(value=1000),
                    ],
                ),
            ),
            ast.Alias(
                alias="inactive_seconds",
                expr=ast.Call(name="minus", args=[ast.Field(chain=["duration"]), ast.Field(chain=["active_seconds"])]),
            ),
            ast.Alias(
                alias="console_log_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "console_log_count"])]),
            ),
            ast.Alias(
                alias="console_warn_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "console_warn_count"])]),
            ),
            ast.Alias(
                alias="console_error_count",
                expr=ast.Call(name="sum", args=[ast.Field(chain=["s", "console_error_count"])]),
            ),
        ]

    def _order_by_clause(self) -> ast.OrderExpr:
        return ast.OrderExpr(expr=ast.Field(chain=[self._filter.order]), order="DESC")

    def _where_predicates(self) -> Union[ast.And, ast.Or]:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["s", "min_first_timestamp"]),
                right=ast.Constant(value=datetime.now() - timedelta(days=self.ttl_days)),
            )
        ]

        person_id_compare_operation = PersonsIdCompareOperation(self._team, self._filter, self.ttl_days).get_operation()
        if person_id_compare_operation:
            exprs.append(person_id_compare_operation)

        # we check for session_ids type not for truthiness since we want to allow empty lists
        if isinstance(self._filter.session_ids, list):
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Constant(value=self._filter.session_ids),
                )
            )

        if self._filter.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=self._filter.date_from),
                )
            )
        if self._filter.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=self._filter.date_to),
                )
            )

        optional_exprs: list[ast.Expr] = []

        # if in PoE mode then we should be pushing person property queries into here
        events_sub_query = ReplayFiltersEventsSubQuery(self._team, self._filter).get_query_for_session_id_matching()
        if events_sub_query:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "session_id"]),
                    right=events_sub_query,
                )
            )

        # we want to avoid a join to persons since we don't ever need to select from them,
        # so we create our own persons sub query here
        # if PoE mode is on then this will be handled in the events subquery, and we don't need to do anything here
        person_subquery = PersonsPropertiesSubQuery(self._team, self._filter, self.ttl_days).get_query()
        if person_subquery:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=person_subquery,
                )
            )

        remaining_properties = self._strip_person_and_event_properties(self._filter.property_groups)
        if remaining_properties:
            logger.info(
                "session_replay_query_builder has unhandled properties", unhandled_properties=remaining_properties
            )
            optional_exprs.append(property_to_expr(remaining_properties, team=self._team, scope="replay"))

        if self._filter.console_log_filters.values:
            console_logs_subquery = ast.SelectQuery(
                select=[ast.Field(chain=["log_source_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
                where=ast.And(
                    exprs=[
                        self._filter.ast_operand(
                            exprs=[
                                property_to_expr(self._filter.console_log_filters, team=self._team),
                            ]
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["log_source"]),
                            right=ast.Constant(value="session_replay"),
                        ),
                    ]
                ),
            )

            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=console_logs_subquery,
                )
            )

        if optional_exprs:
            exprs.append(self._filter.ast_operand(exprs=optional_exprs))

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr:
        return property_to_expr(self._filter.having_predicates, team=self._team, scope="replay")

    def _strip_person_and_event_properties(self, property_group: PropertyGroup) -> PropertyGroup | None:
        property_groups_to_keep = [g for g in property_group.flat if not is_person_property(g)]

        return (
            PropertyGroup(
                type=self._filter.property_operand,
                values=property_groups_to_keep,
            )
            if property_groups_to_keep
            else None
        )


def poe_is_active(team: Team) -> bool:
    return team.person_on_events_mode is not None and team.person_on_events_mode != PersonsOnEventsMode.DISABLED


class PersonsPropertiesSubQuery:
    _team: Team
    _filter: SessionRecordingsFilter
    _ttl_days: int

    def __init__(self, team: Team, filter: SessionRecordingsFilter, ttl_days: int):
        self._team = team
        self._filter = filter
        self._ttl_days = ttl_days

    def get_query(self) -> ast.SelectQuery | ast.SelectUnionQuery | None:
        if self.person_properties and not poe_is_active(self._team):
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE {where_predicates}
                """,
                {
                    "where_predicates": self._where_predicates,
                },
            )
        else:
            return None

    @cached_property
    def person_properties(self) -> PropertyGroup | None:
        person_property_groups = [g for g in self._filter.property_groups.flat if is_person_property(g)]
        return (
            PropertyGroup(
                type=self._filter.property_operand,
                values=person_property_groups,
            )
            if person_property_groups
            else None
        )

    @cached_property
    def _where_predicates(self) -> ast.Expr:
        return (
            property_to_expr(self.person_properties, team=self._team)
            if self.person_properties
            else ast.Constant(value=True)
        )


class PersonsIdCompareOperation:
    _team: Team
    _filter: SessionRecordingsFilter
    _ttl_days: int

    def __init__(self, team: Team, filter: SessionRecordingsFilter, ttl_days: int):
        self._team = team
        self._filter = filter
        self._ttl_days = ttl_days

    def get_operation(self) -> CompareOperation | None:
        q = self.get_query()
        if not q:
            return None

        if poe_is_active(self._team):
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["session_id"]),
                right=q,
            )
        else:
            return ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["distinct_id"]),
                right=q,
            )

    def get_query(self) -> ast.SelectQuery | ast.SelectUnionQuery | None:
        if not self._filter.person_uuid:
            return None

        # anchor to python now so that tests can freeze time
        now = datetime.now()

        if poe_is_active(self._team):
            return parse_select(
                """
                select
                    distinct `$session_id`
                from
                    events
                where
                    person_id = {person_id}
                    and timestamp <= {now}
                    and timestamp >= {ttl_date}
                    and timestamp >= {date_from}
                    and timestamp <= {date_to}
                    and notEmpty(`$session_id`)
                """,
                {
                    "person_id": ast.Constant(value=self._filter.person_uuid),
                    "ttl_days": ast.Constant(value=self._ttl_days),
                    "date_from": ast.Constant(value=self._filter.date_from),
                    "date_to": ast.Constant(value=self._filter.date_to),
                    "now": ast.Constant(value=now),
                    "ttl_date": ast.Constant(value=now - timedelta(days=self._ttl_days)),
                },
            )
        else:
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE person_id = {person_id}
                """,
                {
                    "person_id": ast.Constant(value=self._filter.person_uuid),
                },
            )


class ReplayFiltersEventsSubQuery:
    _team: Team
    _filter: SessionRecordingsFilter

    @property
    def ttl_days(self):
        return ttl_days(self._team)

    def __init__(
        self,
        team: Team,
        filter: SessionRecordingsFilter,
        hogql_query_modifiers: Optional[HogQLQueryModifiers] = None,
    ):
        self._team = team
        self._filter = filter
        self._hogql_query_modifiers = hogql_query_modifiers

    @cached_property
    def _event_predicates(self):
        event_exprs: list[ast.Expr] = []
        event_names: set[int | str] = set()

        for entity in self._filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names.update([ae for ae in action.get_step_events() if ae and ae not in event_names])
            else:
                if entity.id and entity.id not in event_names:
                    event_names.add(entity.id)

            # TODO: we're not passing the "right" type in here - should we change the signature or do something else?
            entity_exprs = [entity_to_expr(entity=entity)]  # type: ignore

            if entity.property_groups:
                entity_exprs.append(property_to_expr(entity.property_groups, team=self._team, scope="replay_entity"))

            event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs, list(event_names)

    def _select_from_events(self, select_expr: ast.Expr) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[select_expr],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
            ),
            where=self._where_predicates(),
            having=self._having_predicates(),
            group_by=[ast.Field(chain=["$session_id"])],
        )

    def get_query_for_session_id_matching(self) -> ast.SelectQuery | ast.SelectUnionQuery | None:
        use_poe = poe_is_active(self._team) and self.person_properties
        if self._filter.entities or use_poe:
            return self._select_from_events(ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])))
        else:
            return None

    def get_query_for_event_id_matching(self) -> ast.SelectQuery | ast.SelectUnionQuery:
        return self._select_from_events(ast.Call(name="groupUniqArray", args=[ast.Field(chain=["uuid"])]))

    def get_event_ids_for_session(self) -> SessionRecordingQueryResult:
        query = self.get_query_for_event_id_matching()

        hogql_query_response = execute_hogql_query(
            query=query,
            team=self._team,
            query_type="SessionRecordingMatchingEventsForSessionQuery",
            modifiers=self._hogql_query_modifiers,
        )

        flattened_results = [str(uuid) for row in hogql_query_response.results for uuid in row[0]]

        return SessionRecordingQueryResult(
            results=flattened_results,
            has_more_recording=False,
            timings=hogql_query_response.timings,
        )

    def _where_predicates(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.Call(
                name="notEmpty",
                args=[ast.Field(chain=["$session_id"])],
            ),
            # regardless of any other filters limit between TTL and current time
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=datetime.now() - timedelta(days=self.ttl_days)),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Call(name="now", args=[]),
            ),
        ]

        # TRICKY: we're adding a buffer to the date range to ensure we get all the events
        # you can start sending us events before the session starts
        if self._filter.date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self._filter.date_from - timedelta(minutes=2)),
                )
            )

        # but we don't want to include events after date_to if provided
        if self._filter.date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self._filter.date_to),
                )
            )

        (event_where_exprs, _) = self._event_predicates
        if event_where_exprs:
            # we OR all events in the where and use hasAll / hasAny in the HAVING clause
            exprs.append(ast.Or(exprs=event_where_exprs))

        if self._team.person_on_events_mode and self.person_properties:
            exprs.append(property_to_expr(self.person_properties, team=self._team, scope="event"))

        if self._filter.session_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["$session_id"]),
                    right=ast.Constant(value=self._filter.session_ids),
                )
            )

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr:
        (_, event_names) = self._event_predicates

        if event_names:
            return ast.Call(
                name="hasAll" if self._filter._operand == "AND" else "hasAny",
                args=[
                    ast.Call(name="groupUniqArray", args=[ast.Field(chain=["event"])]),
                    # KLUDGE: sorting only so that snapshot tests are consistent
                    ast.Constant(value=sorted(event_names)),
                ],
            )

        return ast.Constant(value=True)

    @cached_property
    def person_properties(self) -> PropertyGroup | None:
        person_property_groups = [g for g in self._filter.property_groups.flat if is_person_property(g)]
        return (
            PropertyGroup(
                type=self._filter.property_operand,
                values=person_property_groups,
            )
            if person_property_groups
            else None
        )
