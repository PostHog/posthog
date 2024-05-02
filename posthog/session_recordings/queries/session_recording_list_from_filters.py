from typing import Any, NamedTuple
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import entity_to_expr, property_to_expr
from posthog.models import Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.mixins.utils import cached_property
from posthog.session_recordings.queries.session_replay_events import ttl_days
from posthog.constants import TREND_FILTER_TYPE_ACTIONS


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


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
        LIMIT 10
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
        **_,
    ):
        self._team = team
        self._filter = filter

    @property
    def ttl_days(self):
        return ttl_days(self._team)

    @cached_property
    def _event_predicates(self):
        event_exprs: list[ast.Expr] = []
        event_names: set[int | str] = set()

        for entity in self._filter.entities:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names.update([ae for ae in action.get_step_events() if ae not in event_names])
            else:
                if entity.id and entity.id not in event_names:
                    event_names.add(entity.id)

            # TODO: we're not passing the "right" type in here - should we change the signature or do something else?
            entity_exprs = [entity_to_expr(entity=entity)]  # type: ignore

            if entity.property_groups:
                entity_exprs.append(property_to_expr(entity.property_groups, team=self._team, scope="session"))

            event_exprs.append(ast.And(exprs=entity_exprs))

        return event_exprs, list(event_names)

    def run(self) -> SessionRecordingQueryResult:
        query = parse_select(
            self.BASE_QUERY,
            {
                "order_by": self._order_by_clause(),
                "where_predicates": self._where_predicates(),
                "having_predicates": self._having_predicates(),
            },
        )

        response = execute_hogql_query(
            query=query,
            team=self._team,
        )

        session_recordings = self._data_to_return(response.results)
        return SessionRecordingQueryResult(results=session_recordings, has_more_recording=False)

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
                    left=ast.Field(chain=["s", "max_last_timestamp"]),
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

        (event_where_exprs, _) = self._event_predicates
        if event_where_exprs:
            exprs.append(ast.Or(exprs=event_where_exprs))

        if self._filter.property_groups:
            # TRICKY: for person properties the scope of replay is equivalent to scope event, the session_replay_events schema mirrors events for person joining
            # TODO: need to check multiple property types from replay queries
            exprs.append(property_to_expr(self._filter.property_groups, team=self._team, scope="replay"))

        if self._filter.person_uuid:
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

        (_, event_names) = self._event_predicates
        if event_names:
            exprs.append(
                ast.Call(
                    name="hasAll",
                    args=[
                        ast.Call(name="groupUniqArray", args=[ast.Field(chain=["events", "event"])]),
                        # KLUDGE: sorting only so that snapshot tests are consistent
                        ast.Constant(value=sorted(event_names)),
                    ],
                )
            )

        return ast.And(exprs=exprs) if exprs else Constant(value=True)
