from concurrent.futures import CancelledError
from typing import Any

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryResponse

from posthog.hogql.constants import LimitContext
from posthog.hogql.multi_query import ExecutionGroup, SharingQuery
from posthog.hogql.multi_query_execution import (
    SHARED_EXECUTION_FAILED_REASON,
    FallbackOutcome,
    MultiQueryExecutor,
    SharedOutcome,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

POSTHOG_AI_ROW_CAP = 500
COLUMNS = ["a", "b", "c", "d"]
TYPES = [(column, "UInt64") for column in COLUMNS]


class TestMultiQueryExecutorExecuteGroup(SimpleTestCase):
    def group(self, multi_query: MultiQueryExecutor) -> ExecutionGroup:
        queries = [
            SharingQuery(
                query_id=query_id,
                query=parse_select("SELECT count() AS n FROM events"),
                context_key="request",
                sharing_enabled=True,
            )
            for query_id in ("first", "second")
        ]
        [group] = multi_query.plan(queries).groups
        return group

    def executor(self) -> Mock:
        executor = Mock(spec=HogQLQueryExecutor)
        executor.team = Mock()
        executor.context = Mock()
        executor.query_modifiers = None
        executor.clickhouse_settings = None
        executor.limit_context = LimitContext.POSTHOG_AI
        return executor

    def execute_group(self, multi_query: MultiQueryExecutor, shared: Mock) -> dict[str, Any]:
        with patch("posthog.hogql.multi_query_execution._CancellableExecutor", return_value=shared):
            return multi_query.execute_group(self.executor(), self.group(multi_query))

    @parameterized.expand(
        [
            ("complete", {}, True),
            ("has_more", {"hasMore": True}, False),
            ("error", {"error": "Query failed"}, False),
            ("at_row_cap", {"results": [(7, 7, 7, 7)] * POSTHOG_AI_ROW_CAP}, False),
        ]
    )
    def test_shares_only_complete_results(self, _name: str, overrides: dict[str, Any], shared_ok: bool) -> None:
        shared = Mock()
        shared.execute.return_value = HogQLQueryResponse(
            **{"results": [(7, 7, 7, 7)], "columns": COLUMNS, "types": TYPES, **overrides}
        )

        outcomes = self.execute_group(MultiQueryExecutor(), shared)

        self.assertEqual(set(outcomes), {"first", "second"})
        if shared_ok:
            for outcome in outcomes.values():
                assert isinstance(outcome, SharedOutcome)
                self.assertEqual(outcome.response.results, [(7,)])
        else:
            self.assertEqual(
                outcomes,
                {
                    query_id: FallbackOutcome(
                        query_id=query_id, rule="count_fusion", reason=SHARED_EXECUTION_FAILED_REASON
                    )
                    for query_id in ("first", "second")
                },
            )

    @parameterized.expand([("before_run", True), ("during_run", False)])
    def test_cancellation_raises_instead_of_falling_back(self, _name: str, cancel_before: bool) -> None:
        multi_query = MultiQueryExecutor()
        shared = Mock()
        shared.execute.return_value = HogQLQueryResponse(results=[(7, 7, 7, 7)], columns=COLUMNS, types=TYPES)
        if cancel_before:
            multi_query.cancelled.set()
        else:
            shared.execute.side_effect = CancelledError()

        with self.assertRaises(CancelledError):
            self.execute_group(multi_query, shared)
