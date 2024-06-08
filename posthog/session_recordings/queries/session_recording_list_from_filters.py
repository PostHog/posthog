from typing import Any, NamedTuple, cast, Optional
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.parser import parse_select
from posthog.hogql.property import entity_to_expr, property_to_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyGroup
from posthog.schema import QueryTiming, HogQLQueryModifiers
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, PropertyOperatorType


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool
    timings: list[QueryTiming] | None = None


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _team: Team
    _filter: SessionRecordingsFilter

    BASE_QUERY: str = """
        SELECT s.session_id,
            any(s.team_id),
            any(s.distinct_id),
            min(s.min_first_timestamp) as start_time,
            max(s.max_last_timestamp) as end_time,
            dateDiff('SECOND', start_time, end_time) as duration,
            argMinMerge(s.first_url) as first_url,
            sum(s.click_count),
            sum(s.keypress_count),
            sum(s.mouse_activity_count),
            sum(s.active_milliseconds)/1000 as active_seconds,
            duration-active_seconds as inactive_seconds,
            sum(s.console_log_count) as console_log_count,
            sum(s.console_warn_count) as console_warn_count,
            sum(s.console_error_count) as console_error_count
        FROM raw_session_replay_events s
        WHERE {where_predicates}
        GROUP BY session_id
        HAVING {having_predicates}
        ORDER BY {order_by} DESC
        """

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
        query = parse_select(
            self.BASE_QUERY,
            {
                "order_by": self._order_by_clause(),
                "where_predicates": self._where_predicates(),
                "having_predicates": self._having_predicates(),
            },
        )

        paginated_response = self._paginator.execute_hogql_query(
            # TODO I guess the paginator needs to know how to handle union queries or all callers are supposed to collapse them or .... 🤷
            query=cast(ast.SelectQuery, query),
            team=self._team,
            # TODO - should we have our own query type 🤷
            query_type="hogql_query",
            modifiers=self._hogql_query_modifiers,
        )

        return SessionRecordingQueryResult(
            results=(self._data_to_return(self._paginator.results)),
            has_more_recording=self._paginator.has_more(),
            timings=paginated_response.timings,
        )

    def _order_by_clause(self) -> ast.Field:
        order = self._filter.target_entity_order or "start_time"
        return ast.Field(chain=[order])

    def _where_predicates(self) -> ast.And:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["s", "min_first_timestamp"]),
                right=ast.Constant(value=datetime.now() - timedelta(days=self.ttl_days)),
            )
        ]

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

        if self._filter.session_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Constant(value=self._filter.session_ids),
                )
            )

        if self._filter.entities:
            events_sub_query = EventsSubQuery(self._team, self._filter, self.ttl_days).get_query()
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "session_id"]),
                    right=events_sub_query,
                )
            )

        # other_property_groups, person_property_groups = self._split_property_groups(self._filter.property_groups)
        # if person_property_groups:
        #     persons_sub_query = PersonsSubQuery(self._team, self._filter, self.ttl_days).get_query()
        #     exprs.append(
        #         ast.CompareOperation(
        #             op=ast.CompareOperationOp.In,
        #             left=ast.Field(chain=["s", "distinct_id"]),
        #             right=persons_sub_query,
        #         )
        #     )

        # we want to avoid a join to persons since we don't ever need to select from them
        person_subquery = PersonsSubQuery(self._team, self._filter, self.ttl_days).get_query()
        if person_subquery:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=person_subquery,
                )
            )

        non_person_properties = self._strip_person_properties(self._filter.property_groups)
        if non_person_properties:
            exprs.append(property_to_expr(non_person_properties, team=self._team, scope="replay"))

        if self._filter.person_uuid:
            # TODO this will probably generate a join too, so we can optimise that away
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["person_id"]),
                    right=ast.Constant(value=self._filter.person_uuid),
                )
            )

        console_logs_predicates: list[ast.Expr] = []
        if self._filter.console_logs_filter:
            console_logs_predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["level"]),
                    right=ast.Constant(value=self._filter.console_logs_filter),
                )
            )

        if self._filter.console_search_query:
            console_logs_predicates.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Call(
                        name="positionCaseInsensitive",
                        args=[
                            ast.Field(chain=["message"]),
                            ast.Constant(value=self._filter.console_search_query),
                        ],
                    ),
                    right=ast.Constant(value=0),
                )
            )

        if console_logs_predicates:
            console_logs_subquery = ast.SelectQuery(
                select=[ast.Field(chain=["log_source_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
                where=ast.And(exprs=console_logs_predicates),
            )

            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=console_logs_subquery,
                )
            )

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.And | Constant:
        exprs: list[ast.Expr] = []

        if self._filter.recording_duration_filter:
            op = (
                ast.CompareOperationOp.GtEq
                if self._filter.recording_duration_filter.operator == "gt"
                else ast.CompareOperationOp.LtEq
            )
            exprs.append(
                ast.CompareOperation(
                    op=op,
                    left=ast.Field(chain=[self._filter.duration_type_filter]),
                    right=ast.Constant(value=self._filter.recording_duration_filter.value),
                ),
            )

        return ast.And(exprs=exprs) if exprs else Constant(value=True)

    def _strip_person_properties(self, property_group: PropertyGroup) -> PropertyGroup | None:
        property_groups_to_keep = [g for g in property_group.flat if g.type != "person" in g.type]

        return (
            PropertyGroup(
                type=PropertyOperatorType.AND,
                values=property_groups_to_keep,
            )
            if property_groups_to_keep
            else None
        )


class PersonsSubQuery:
    _team: Team
    _filter: SessionRecordingsFilter
    _ttl_days: int

    def __init__(self, team: Team, filter: SessionRecordingsFilter, ttl_days: int):
        self._team = team
        self._filter = filter
        self._ttl_days = ttl_days

    def get_query(self) -> ast.SelectQuery | None:
        if self.person_properties:
            return parse_select(
                """
                SELECT distinct_id
                FROM person_distinct_ids
                WHERE {where_predicates}
                """,
                {
                    "where_predicates": self._where_predicates(),
                },
            )
        else:
            return None

    @cached_property
    def person_properties(self) -> PropertyGroup | None:
        person_property_groups = [g for g in self._filter.property_groups.flat if g.type == "person" in g.type]
        return (
            PropertyGroup(
                type=PropertyOperatorType.AND,
                values=person_property_groups,
            )
            if person_property_groups
            else None
        )

    def _where_predicates(self):
        return property_to_expr(self.person_properties, team=self._team, scope="replay_pdi")


class EventsSubQuery:
    _team: Team
    _filter: SessionRecordingsFilter
    _ttl_days: int

    def __init__(self, team: Team, filter: SessionRecordingsFilter, ttl_days: int):
        self._team = team
        self._filter = filter
        self._ttl_days = ttl_days

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

    def get_query(self):
        return ast.SelectQuery(
            select=[ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._where_predicates(),
            having=self._having_predicates(),
            group_by=[ast.Field(chain=["$session_id"])],
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
                right=ast.Constant(value=datetime.now() - timedelta(days=self._ttl_days)),
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
            exprs.append(ast.Or(exprs=event_where_exprs))

        if self._filter.session_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Constant(value="`$session_id`"),
                    right=ast.Constant(value=self._filter.session_ids),
                )
            )

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr:
        (_, event_names) = self._event_predicates

        if event_names:
            return ast.Call(
                name="hasAll",
                args=[
                    ast.Call(name="groupUniqArray", args=[ast.Field(chain=["event"])]),
                    # KLUDGE: sorting only so that snapshot tests are consistent
                    ast.Constant(value=sorted(event_names)),
                ],
            )

        return ast.Constant(value=True)
