from typing import Any, NamedTuple, Union
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.property import entity_to_expr
from posthog.models import Entity, Team
from posthog.models.action.util import format_entity_filter
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.session_recordings.queries.session_replay_events import ttl_days


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _team: Team
    _filter: SessionRecordingsFilter

    SAMPLE_QUERY: str = """
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
    def _data_to_return(results: list[Any]) -> list[dict[str, Any]]:
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
            for row in results
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

    def run(self) -> SessionRecordingQueryResult:
        # query = parse_select(
        #     self.SAMPLE_QUERY,
        #     {
        #         "order_by": self._order_by_clause(),
        #         "where_predicates": self._where_predicates(),
        #         "having_predicates": self._having_predicates(),
        #     },
        # )

        query = parse_select(
            "select session_id, any(events.properties.$browser) from raw_session_replay_events group by session_id order by session_id asc"
        )

        response = execute_hogql_query(
            query=query,
            team=self._team,
        )

        print("results:")
        print(response.results)
        print(response.hogql)

        session_recordings = self._data_to_return(response.results)
        return SessionRecordingQueryResult(results=session_recordings, has_more_recording=False)

    def _order_by_clause(self) -> Constant:
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

        if self._filter.entities:
            (event_names, event_exprs) = self._event_where_predicates(self._filter.entities)
            exprs.append(ast.Or(exprs=event_exprs))
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["events", "event"]),
                    right=ast.Constant(value=event_names),
                )
            )

        # we need to combine search by console message and log level
        # since if someone filters for text = "foo bar" and level = "info"
        # it doesn't make sense to return all "info" logs and all logs with "foo bar"
        log_level_condition = ast.Constant(value=True)
        if self._filter.console_logs_filter:
            log_level_condition = ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["console_logs", "level"]),
                right=ast.Constant(value=self._filter.console_logs_filter),
            )

        log_message_condition = ast.Constant(value=True)
        if self._filter.console_search_query:
            log_message_condition = ast.CompareOperation(
                op=ast.CompareOperationOp.Gt,
                left=ast.Call(
                    name="positionCaseInsensitive",
                    args=[
                        ast.Field(chain=["console_logs", "message"]),
                        ast.Constant(value=self._filter.console_search_query),
                    ],
                ),
                right=ast.Constant(value=0),
            )

        exprs.append(ast.And(exprs=[log_level_condition, log_message_condition]))

        return ast.And(exprs=exprs)

    def _event_where_predicates(self, entities: list[Entity]) -> ast.Or:
        event_names: list[Union[int, str]] = []
        event_exprs: list[ast.Expr] = []

        for entity in entities:
            event_exprs.append(entity_to_expr(entity=entity))

            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                event_names.extend([ae for ae in action.get_step_events() if ae not in event_names])
            else:
                if entity.id and entity.id not in event_names:
                    event_names.append(entity.id)

        return event_names, event_exprs

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
