from typing import Any, cast, Optional, Union
from datetime import datetime, timedelta, UTC

from posthog.hogql import ast

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team
from posthog.schema import (
    HogQLQueryModifiers,
    RecordingsQuery,
    PropertyGroupFilterValue,
    FilterLogicalOperator,
    RecordingOrder,
)

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.session_recordings.queries_to_replace.sub_queries.base_query import SessionRecordingsListingBaseQuery
from posthog.session_recordings.queries_to_replace.sub_queries.cohort_subquery import CohortPropertyGroupsSubQuery
from posthog.session_recordings.queries_to_replace.sub_queries.events_subquery import ReplayFiltersEventsSubQuery
from posthog.session_recordings.queries_to_replace.sub_queries.person_ids_subquery import PersonsIdCompareOperation
from posthog.session_recordings.queries_to_replace.sub_queries.person_props_subquery import PersonsPropertiesSubQuery
from posthog.session_recordings.queries_to_replace.utils import (
    SessionRecordingQueryResult,
    UnexpectedQueryProperties,
    _strip_person_and_event_and_cohort_properties,
    expand_test_account_filters,
)

logger = structlog.get_logger(__name__)


class SessionRecordingListFromQuery(SessionRecordingsListingBaseQuery):
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    _team: Team
    _query: RecordingsQuery

    BASE_QUERY: str = """
        SELECT s.session_id,
            any(s.team_id),
            any(s.distinct_id),
            min(s.min_first_timestamp) as start_time,
            max(s.max_last_timestamp) as end_time,
            dateDiff('SECOND', start_time, end_time) as duration,
            argMinMerge(s.first_url) as first_url,
            sum(s.click_count) as click_count,
            sum(s.keypress_count) as keypress_count,
            sum(s.mouse_activity_count) as mouse_activity_count,
            sum(s.active_milliseconds)/1000 as active_seconds,
            (duration - active_seconds) as inactive_seconds,
            sum(s.console_log_count) as console_log_count,
            sum(s.console_warn_count) as console_warn_count,
            sum(s.console_error_count) as console_error_count,
            {ongoing_selection},
            round((
            ((sum(s.active_milliseconds) / 1000 + sum(s.click_count) + sum(s.keypress_count) + sum(s.console_error_count))) -- intent
            /
            ((sum(s.mouse_activity_count) + dateDiff('SECOND', start_time, end_time) + sum(s.console_error_count) + sum(s.console_log_count) + sum(s.console_warn_count)))
            * 100
            ), 2) as activity_score
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
            "ongoing",
            "activity_score",
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
        query: RecordingsQuery,
        hogql_query_modifiers: Optional[HogQLQueryModifiers],
        **_,
    ):
        # TRICKY: we need to make sure we init test account filters only once,
        # otherwise we'll end up with a lot of duplicated test account filters in the query
        expanded_query = query.model_copy(deep=True)
        if expanded_query.filter_test_accounts:
            expanded_query.properties = expand_test_account_filters(team) + (expanded_query.properties or [])

        super().__init__(team, expanded_query)

        self._paginator = HogQLHasMorePaginator(
            limit=expanded_query.limit or self.SESSION_RECORDINGS_DEFAULT_LIMIT, offset=expanded_query.offset or 0
        )
        self._hogql_query_modifiers = hogql_query_modifiers

    def run(self) -> SessionRecordingQueryResult:
        query = self.get_query()

        paginated_response = self._paginator.execute_hogql_query(
            # TODO I guess the paginator needs to know how to handle union queries or all callers are supposed to collapse them or .... 🤷
            query=cast(ast.SelectQuery, query),
            team=self._team,
            query_type="SessionRecordingListQuery",
            modifiers=self._hogql_query_modifiers,
            settings=HogQLGlobalSettings(allow_experimental_analyzer=False),  # This needs to be turned on eventually
        )

        return SessionRecordingQueryResult(
            results=(self._data_to_return(self._paginator.results)),
            has_more_recording=self._paginator.has_more(),
            timings=paginated_response.timings,
        )

    def get_query(self):
        return parse_select(
            self.BASE_QUERY,
            {
                # Check if the most recent _timestamp is within five minutes of the current time
                # proxy for a live session
                "ongoing_selection": ast.Alias(
                    alias="ongoing",
                    expr=ast.CompareOperation(
                        left=ast.Call(name="max", args=[ast.Field(chain=["s", "_timestamp"])]),
                        right=ast.Constant(
                            # provided in a placeholder, so we can pass now from python to make tests easier 🙈
                            value=datetime.now(UTC) - timedelta(minutes=5),
                        ),
                        op=ast.CompareOperationOp.GtEq,
                    ),
                ),
                "order_by": self._order_by_clause(),
                "where_predicates": self._where_predicates(),
                "having_predicates": self._having_predicates() or ast.Constant(value=True),
            },
        )

    def _order_by_clause(self) -> ast.Field:
        # KLUDGE: we only need a default here because mypy is silly
        order_by = self._query.order.value if self._query.order else RecordingOrder.START_TIME
        return ast.Field(chain=[order_by])

    def _where_predicates(self) -> Union[ast.And, ast.Or]:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["s", "min_first_timestamp"]),
                right=ast.Constant(value=datetime.now(UTC) - timedelta(days=self.ttl_days)),
            )
        ]

        if self._query.distinct_ids:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["distinct_id"]),
                    right=ast.Constant(value=self._query.distinct_ids),
                )
            )
        else:
            person_id_compare_operation = PersonsIdCompareOperation(self._team, self._query).get_operation()
            if person_id_compare_operation:
                exprs.append(person_id_compare_operation)

        # we check for session_ids type not for truthiness since we want to allow empty lists
        if isinstance(self._query.session_ids, list):
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["session_id"]),
                    right=ast.Constant(value=self._query.session_ids),
                )
            )

        query_date_from = self.query_date_range.date_from()
        if query_date_from:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=query_date_from),
                )
            )

        query_date_to = self.query_date_range.date_to()
        if query_date_to:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["s", "min_first_timestamp"]),
                    right=ast.Constant(value=query_date_to),
                )
            )

        optional_exprs: list[ast.Expr] = []

        # if in PoE mode then we should be pushing person property queries into here
        events_sub_queries = ReplayFiltersEventsSubQuery(self._team, self._query).get_queries_for_session_id_matching()
        for events_sub_query in events_sub_queries:
            optional_exprs.append(
                ast.CompareOperation(
                    # this hits the distributed events table from the distributed session_replay_events table
                    # so we should use GlobalIn
                    # see https://clickhouse.com/docs/en/sql-reference/operators/in#distributed-subqueries
                    op=ast.CompareOperationOp.GlobalIn,
                    left=ast.Field(chain=["s", "session_id"]),
                    right=events_sub_query,
                )
            )

        # we want to avoid a join to persons since we don't ever need to select from them,
        # so we create our own persons sub query here
        # if PoE mode is on then this will be handled in the events subquery, and we don't need to do anything here
        person_subquery = PersonsPropertiesSubQuery(self._team, self._query).get_query()
        if person_subquery:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=person_subquery,
                )
            )

        cohort_subquery = CohortPropertyGroupsSubQuery(self._team, self._query).get_query()
        if cohort_subquery:
            optional_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["s", "distinct_id"]),
                    right=cohort_subquery,
                )
            )

        remaining_properties = _strip_person_and_event_and_cohort_properties(self._query.properties)
        if remaining_properties:
            capture_exception(UnexpectedQueryProperties(remaining_properties))
            optional_exprs.append(property_to_expr(remaining_properties, team=self._team, scope="replay"))

        if self._query.console_log_filters:
            console_logs_subquery = ast.SelectQuery(
                select=[ast.Field(chain=["log_source_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["console_logs_log_entries"])),
                where=property_to_expr(
                    # convert to a property group so we can insert the correct operand
                    PropertyGroupFilterValue(
                        type=(
                            FilterLogicalOperator.AND_ if self.property_operand == "AND" else FilterLogicalOperator.OR_
                        ),
                        values=self._query.console_log_filters,
                    ),
                    team=self._team,
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
            exprs.append(self.wrapped_with_query_operand(exprs=optional_exprs))

        return ast.And(exprs=exprs)

    def _having_predicates(self) -> ast.Expr | None:
        return (
            property_to_expr(self._query.having_predicates, team=self._team, scope="replay")
            if self._query.having_predicates
            else None
        )
