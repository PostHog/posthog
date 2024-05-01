from posthog.models import Team
from typing import Any, NamedTuple
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.parser import parse_select
from posthog.hogql.ast import Constant
from posthog.hogql import ast
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    team: Team
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
        self.team = team
        self._filter = filter

    def run(self) -> SessionRecordingQueryResult:
        query = parse_select(
            self.SAMPLE_QUERY,
            {
                "order_by": Constant(value=self._filter.target_entity_order),
                "where_predicates": self._where_predicates(),
                "having_predicates": self._having_predicates(),
            },
        )

        response = execute_hogql_query(
            query=query,
            team=self.team,
        )

        session_recordings = self._data_to_return(response.results)
        return SessionRecordingQueryResult(results=session_recordings, has_more_recording=False)

    def _where_predicates(self) -> ast.And:
        exprs: list[ast.Expr] = []

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

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.And:
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

        return ast.And(exprs=exprs)
