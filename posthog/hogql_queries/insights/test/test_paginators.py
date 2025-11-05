from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import ActorsQuery, PersonPropertyFilter, PropertyOperator

from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import (
    MAX_SELECT_RETURNED_ROWS,
    LimitContext,
    get_default_limit_for_context,
    get_max_limit_for_context,
)
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models.utils import UUIDT


class TestHogQLHasMorePaginator(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None
    random_uuid: str

    def _create_random_persons(self) -> str:
        random_uuid = f"RANDOM_TEST_ID::{UUIDT()}"
        for index in range(10):
            _create_person(
                properties={
                    "email": f"jacob{index}@{random_uuid}.posthog.com",
                    "name": f"Mr Jacob {random_uuid}",
                    "random_uuid": random_uuid,
                    "index": index,
                },
                team=self.team,
                distinct_ids=[f"id-{random_uuid}-{index}"],
                is_identified=True,
            )
            _create_event(
                distinct_id=f"id-{random_uuid}-{index}",
                event=f"clicky-{index}",
                team=self.team,
            )

        flush_persons_and_events()
        return random_uuid

    def _create_runner(self, query: ActorsQuery) -> ActorsQueryRunner:
        return ActorsQueryRunner(team=self.team, query=query)

    def setUp(self):
        super().setUp()
        self.random_uuid = self._create_random_persons()

    def test_persons_query_limit(self):
        runner = self._create_runner(
            ActorsQuery(select=["properties.email"], orderBy=["properties.email DESC"], limit=1)
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob9@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

        runner = self._create_runner(
            ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                limit=1,
                offset=2,
            )
        )
        response = runner.calculate()
        self.assertEqual(response.results, [[f"jacob7@{self.random_uuid}.posthog.com"]])
        self.assertEqual(response.hasMore, True)

    def test_zero_limit(self):
        """Test behavior with limit set to zero."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=0))
        response = runner.calculate()
        self.assertEqual(runner.paginator.limit, 100)
        self.assertEqual(response.limit, 100)
        self.assertEqual(len(response.results), 10)
        self.assertFalse(response.hasMore)

    def test_negative_limit(self):
        """Test behavior with negative limit value."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=-1))
        response = runner.calculate()
        self.assertEqual(runner.paginator.limit, 100)
        self.assertEqual(response.limit, 100)
        self.assertEqual(len(response.results), 10)
        self.assertFalse(response.hasMore)

    def test_exact_limit_match(self):
        """Test when available items equal the limit."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=10))
        response = runner.calculate()
        self.assertEqual(len(response.results), 10)
        self.assertFalse(response.hasMore)

    def test_empty_result_set(self):
        """Test behavior when query returns no results."""
        runner = self._create_runner(
            ActorsQuery(
                select=["properties.email"],
                limit=10,
                properties=[
                    PersonPropertyFilter(key="email", value="random", operator=PropertyOperator.EXACT),
                ],
            )
        )
        response = runner.calculate()
        self.assertEqual(len(response.results), 0)
        self.assertFalse(response.hasMore)

    def test_large_offset(self):
        """Test behavior with offset larger than the total number of items."""
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=5, offset=100))
        response = runner.calculate()
        self.assertEqual(len(response.results), 0)
        self.assertFalse(response.hasMore)

    def test_offset_plus_limit_exceeding_total(self):
        """Test when sum of offset and limit exceeds total items."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=10, offset=5))
        response = runner.calculate()
        self.assertEqual(runner.paginator.offset, 5)
        self.assertEqual(len(response.results), 5)
        self.assertFalse(response.hasMore)

    def test_response_params_consistency(self):
        """Test consistency of response_params method."""
        paginator = HogQLHasMorePaginator(limit=5, offset=10)
        paginator.response = paginator.execute_hogql_query(
            cast(SelectQuery, parse_select("SELECT * FROM persons")),
            query_type="test_query",
            team=self.team,
        )
        params = paginator.response_params()
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["offset"], 10)
        self.assertEqual(params["hasMore"], paginator.has_more())

    def test_handle_none_response(self):
        """Test handling of None response."""
        paginator = HogQLHasMorePaginator(limit=5, offset=0)
        paginator.response = None  # Simulate a None response
        self.assertEqual(paginator.trim_results(), [])
        self.assertFalse(paginator.has_more())

    def test_limit_context_variations(self):
        limit_context = LimitContext.QUERY

        test_cases = [
            {
                "limit": 5,
                "offset": 10,
                "expected_limit": 5,
                "expected_offset": 10,
            },
            {
                "limit": None,
                "offset": 10,
                "expected_limit": get_default_limit_for_context(limit_context),
                "expected_offset": 10,
            },
            {
                "limit": 0,
                "offset": 10,
                "expected_limit": get_default_limit_for_context(limit_context),
                "expected_offset": 10,
            },
            {
                "limit": -1,
                "offset": 10,
                "expected_limit": get_default_limit_for_context(limit_context),
                "expected_offset": 10,
            },
            {
                "limit": MAX_SELECT_RETURNED_ROWS,
                "offset": 10,
                "expected_limit": get_max_limit_for_context(limit_context),
                "expected_offset": 10,
            },
            {
                "limit": 5,
                "offset": None,
                "expected_limit": 5,
                "expected_offset": 0,
            },
            {
                "limit": 5,
                "offset": -1,
                "expected_limit": 5,
                "expected_offset": 0,
            },
        ]

        for case in test_cases:
            with self.subTest(case=case):
                paginator = HogQLHasMorePaginator.from_limit_context(
                    limit_context=limit_context, limit=case["limit"], offset=case["offset"]
                )
                self.assertEqual(paginator.limit, case["expected_limit"])
                self.assertEqual(paginator.offset, case["expected_offset"])

    @patch("posthog.hogql_queries.insights.paginators.execute_hogql_query")
    def test_passes_limit_context(self, mock_execute_hogql_query: MagicMock):
        limit_context = LimitContext.EXPORT
        paginator = HogQLHasMorePaginator.from_limit_context(limit_context=limit_context, limit=5, offset=10)
        paginator.execute_hogql_query(
            query=cast(SelectQuery, parse_select("SELECT * FROM persons")), query_type="query type"
        )
        mock_execute_hogql_query.assert_called_once()
        self.assertEqual(mock_execute_hogql_query.call_args.kwargs["limit_context"], limit_context)
