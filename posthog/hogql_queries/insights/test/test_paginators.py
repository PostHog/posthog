import json
import base64
from typing import cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import MagicMock, patch

from posthog.schema import ActorsQuery, PersonPropertyFilter, PropertyOperator

from posthog.hogql.ast import And, CompareOperation, Constant, SelectQuery
from posthog.hogql.constants import (
    MAX_SELECT_RETURNED_ROWS,
    LimitContext,
    get_default_limit_for_context,
    get_max_limit_for_context,
)
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLCursorPaginator, HogQLHasMorePaginator
from posthog.models.utils import UUIDT
import pytest


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
        assert response.results == [[f"jacob9@{self.random_uuid}.posthog.com"]]
        assert response.hasMore == True

        runner = self._create_runner(
            ActorsQuery(
                select=["properties.email"],
                orderBy=["properties.email DESC"],
                limit=1,
                offset=2,
            )
        )
        response = runner.calculate()
        assert response.results == [[f"jacob7@{self.random_uuid}.posthog.com"]]
        assert response.hasMore == True

    def test_zero_limit(self):
        """Test behavior with limit set to zero."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=0))
        response = runner.calculate()
        assert runner.paginator.limit == 100
        assert response.limit == 100
        assert len(response.results) == 10
        assert not response.hasMore

    def test_negative_limit(self):
        """Test behavior with negative limit value."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=-1))
        response = runner.calculate()
        assert runner.paginator.limit == 100
        assert response.limit == 100
        assert len(response.results) == 10
        assert not response.hasMore

    def test_exact_limit_match(self):
        """Test when available items equal the limit."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=10))
        response = runner.calculate()
        assert len(response.results) == 10
        assert not response.hasMore

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
        assert len(response.results) == 0
        assert not response.hasMore

    def test_large_offset(self):
        """Test behavior with offset larger than the total number of items."""
        self.random_uuid = self._create_random_persons()
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=5, offset=100))
        response = runner.calculate()
        assert len(response.results) == 0
        assert not response.hasMore

    def test_offset_plus_limit_exceeding_total(self):
        """Test when sum of offset and limit exceeds total items."""
        runner = self._create_runner(ActorsQuery(select=["properties.email"], limit=10, offset=5))
        response = runner.calculate()
        assert runner.paginator.offset == 5
        assert len(response.results) == 5
        assert not response.hasMore

    def test_response_params_consistency(self):
        """Test consistency of response_params method."""
        paginator = HogQLHasMorePaginator(limit=5, offset=10)
        paginator.response = paginator.execute_hogql_query(
            cast(SelectQuery, parse_select("SELECT * FROM persons")),
            query_type="test_query",
            team=self.team,
        )
        params = paginator.response_params()
        assert params["limit"] == 5
        assert params["offset"] == 10
        assert params["hasMore"] == paginator.has_more()

    def test_handle_none_response(self):
        """Test handling of None response."""
        paginator = HogQLHasMorePaginator(limit=5, offset=0)
        paginator.response = None  # Simulate a None response
        assert paginator.trim_results() == []
        assert not paginator.has_more()

    def test_limit_context_variations(self):
        limit_context = LimitContext.QUERY

        test_cases: list[dict[str, int | None]] = [
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
                assert paginator.limit == case["expected_limit"]
                assert paginator.offset == case["expected_offset"]

    @patch("posthog.hogql_queries.insights.paginators.execute_hogql_query")
    def test_passes_limit_context(self, mock_execute_hogql_query: MagicMock):
        limit_context = LimitContext.EXPORT
        paginator = HogQLHasMorePaginator.from_limit_context(limit_context=limit_context, limit=5, offset=10)
        paginator.execute_hogql_query(
            query=cast(SelectQuery, parse_select("SELECT * FROM persons")), query_type="query type"
        )
        mock_execute_hogql_query.assert_called_once()
        assert mock_execute_hogql_query.call_args.kwargs["limit_context"] == limit_context


class TestHogQLCursorPaginator(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_cursor_encoding_decoding(self):
        """Test that cursor is properly encoded and decoded"""
        from datetime import datetime

        cursor_data = {"order_value": "2025-01-06 12:00:00", "session_id": "session_123"}
        json_str = json.dumps(cursor_data)
        cursor = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        paginator = HogQLCursorPaginator(limit=10, after=cursor, order_field="start_time", order_direction="DESC")

        assert paginator.cursor_data is not None
        assert paginator.cursor_data is not None  # Type narrowing for mypy
        # The cursor decoder automatically parses datetime strings back to datetime objects
        assert paginator.cursor_data["order_value"] == datetime(2025, 1, 6, 12, 0)
        assert paginator.cursor_data["session_id"] == "session_123"

    def test_invalid_cursor_raises_error(self):
        """Test that invalid cursor format raises ValueError"""
        with pytest.raises(ValueError) as context:
            HogQLCursorPaginator(limit=10, after="invalid_cursor", order_field="start_time", order_direction="DESC")
        assert "Invalid cursor format" in str(context.value)

    def test_cursor_extraction_from_dict_results(self):
        """Test cursor extraction when results are dicts"""
        paginator = HogQLCursorPaginator(limit=5, order_field="start_time", order_direction="DESC")

        # Simulate results with has_more
        paginator.results = [
            {"session_id": "s1", "start_time": "2025-01-06 10:00:00"},
            {"session_id": "s2", "start_time": "2025-01-06 09:00:00"},
            {"session_id": "s3", "start_time": "2025-01-06 08:00:00"},
            {"session_id": "s4", "start_time": "2025-01-06 07:00:00"},
            {"session_id": "s5", "start_time": "2025-01-06 06:00:00"},
        ]
        # Mock response to trigger has_more
        paginator.response = MagicMock()
        paginator.response.results = [*paginator.results, {"extra": "item"}]  # 6 items means has_more

        cursor = paginator.get_next_cursor()

        assert cursor is not None
        assert cursor is not None  # Type narrowing for mypy
        decoded = json.loads(base64.b64decode(cursor).decode("utf-8"))
        assert decoded["session_id"] == "s5"
        assert decoded["order_value"] == "2025-01-06 06:00:00"

    def test_cursor_extraction_from_tuple_results_with_field_indices(self):
        """Test cursor extraction when results are tuples using field_indices"""
        field_indices = {
            "session_id": 0,
            "team_id": 1,
            "distinct_id": 2,
            "start_time": 3,
            "duration": 5,
            "console_error_count": 14,
        }

        # Test with start_time ordering
        paginator = HogQLCursorPaginator(
            limit=3, order_field="start_time", order_direction="DESC", field_indices=field_indices
        )
        paginator.results = [
            ("s1", 1, "d1", "2025-01-06 10:00:00", "2025-01-06 11:00:00", 3600, None, 0, 0, 0, 3000, 600, 0, 0, 5),
            ("s2", 1, "d2", "2025-01-06 09:00:00", "2025-01-06 10:00:00", 3600, None, 0, 0, 0, 3000, 600, 0, 0, 3),
            ("s3", 1, "d3", "2025-01-06 08:00:00", "2025-01-06 09:00:00", 3600, None, 0, 0, 0, 3000, 600, 0, 0, 2),
        ]
        paginator.response = MagicMock()
        paginator.response.results = [*paginator.results, ("extra",)]

        cursor = paginator.get_next_cursor()
        assert cursor is not None  # Type narrowing for mypy
        decoded = json.loads(base64.b64decode(cursor).decode("utf-8"))
        assert decoded["session_id"] == "s3"
        assert decoded["order_value"] == "2025-01-06 08:00:00"

        # Test with console_error_count ordering (different field)
        paginator2 = HogQLCursorPaginator(
            limit=3, order_field="console_error_count", order_direction="DESC", field_indices=field_indices
        )
        paginator2.results = paginator.results
        paginator2.response = MagicMock()
        paginator2.response.results = [*paginator2.results, ("extra",)]

        cursor2 = paginator2.get_next_cursor()
        assert cursor2 is not None  # Type narrowing for mypy
        decoded2 = json.loads(base64.b64decode(cursor2).decode("utf-8"))
        assert decoded2["session_id"] == "s3"
        assert decoded2["order_value"] == 2  # console_error_count is at index 13

    def test_no_cursor_when_no_more_results(self):
        """Test that cursor is None when there are no more results"""
        paginator = HogQLCursorPaginator(limit=5, order_field="start_time", order_direction="DESC")
        paginator.results = [
            {"session_id": "s1", "start_time": "2025-01-06 10:00:00"},
            {"session_id": "s2", "start_time": "2025-01-06 09:00:00"},
        ]
        paginator.response = MagicMock()
        paginator.response.results = paginator.results  # Only 2 items, limit is 5, so no more

        cursor = paginator.get_next_cursor()
        assert cursor is None

    def test_where_clause_generation_desc(self):
        """Test that WHERE clause is correctly generated for DESC ordering"""
        cursor_data = {"order_value": "2025-01-06 12:00:00", "session_id": "session_123"}
        json_str = json.dumps(cursor_data)
        cursor = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        paginator = HogQLCursorPaginator(limit=10, after=cursor, order_field="start_time", order_direction="DESC")

        query = cast(SelectQuery, parse_select("SELECT session_id, start_time FROM events"))
        paginated_query = cast(SelectQuery, paginator.paginate(query))

        # Check that WHERE clause was added
        assert paginated_query.where is not None
        assert paginated_query.where is not None  # Type narrowing for mypy
        where_clause = cast(CompareOperation, paginated_query.where)
        assert where_clause.op.name == "Lt"  # Less than for DESC

    def test_where_clause_generation_asc(self):
        """Test that WHERE clause is correctly generated for ASC ordering"""
        cursor_data = {"order_value": "2025-01-06 12:00:00", "session_id": "session_123"}
        json_str = json.dumps(cursor_data)
        cursor = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        paginator = HogQLCursorPaginator(limit=10, after=cursor, order_field="start_time", order_direction="ASC")

        query = cast(SelectQuery, parse_select("SELECT session_id, start_time FROM events"))
        paginated_query = cast(SelectQuery, paginator.paginate(query))

        # Check that WHERE clause was added
        assert paginated_query.where is not None
        assert paginated_query.where is not None  # Type narrowing for mypy
        where_clause = cast(CompareOperation, paginated_query.where)
        assert where_clause.op.name == "Gt"  # Greater than for ASC

    def test_where_clause_combines_with_existing(self):
        """Test that cursor WHERE clause is combined with existing WHERE clause"""
        cursor_data = {"order_value": "2025-01-06 12:00:00", "session_id": "session_123"}
        json_str = json.dumps(cursor_data)
        cursor = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        paginator = HogQLCursorPaginator(limit=10, after=cursor, order_field="start_time", order_direction="DESC")

        query = cast(SelectQuery, parse_select("SELECT session_id, start_time FROM events WHERE team_id = 1"))
        paginated_query = cast(SelectQuery, paginator.paginate(query))

        # Check that WHERE clause is now an AND combining both conditions
        assert paginated_query.where is not None
        assert paginated_query.where is not None  # Type narrowing for mypy
        assert isinstance(paginated_query.where, And)
        where_clause = cast(And, paginated_query.where)
        assert len(where_clause.exprs) == 2  # Should combine 2 conditions

    def test_limit_plus_one_for_has_more_detection(self):
        """Test that paginator fetches limit+1 to detect has_more"""
        paginator = HogQLCursorPaginator(limit=10, order_field="start_time", order_direction="DESC")

        query = cast(SelectQuery, parse_select("SELECT session_id FROM events"))
        paginated_query = cast(SelectQuery, paginator.paginate(query))

        # Check that limit is set to limit+1
        assert paginated_query.limit is not None  # Type narrowing for mypy
        limit_value = cast(Constant, paginated_query.limit)
        assert limit_value.value == 11

    def test_has_more_detection(self):
        """Test has_more is correctly detected when results exceed limit"""
        paginator = HogQLCursorPaginator(limit=5, order_field="start_time", order_direction="DESC")

        # Mock response with 6 results (limit+1)
        paginator.response = MagicMock()
        paginator.response.results = [{"id": i} for i in range(6)]

        assert paginator.has_more()

        # Test with exactly limit results
        paginator.response.results = [{"id": i} for i in range(5)]
        assert not paginator.has_more()

    def test_trim_results_removes_extra_item(self):
        """Test that trim_results removes the extra item used for has_more detection"""
        paginator = HogQLCursorPaginator(limit=5, order_field="start_time", order_direction="DESC")

        # Mock response with 6 results
        paginator.response = MagicMock()
        paginator.response.results = [{"id": i} for i in range(6)]

        trimmed = paginator.trim_results()

        assert len(trimmed) == 5
        assert {"id": 5} not in trimmed

    def test_response_params_includes_next_cursor(self):
        """Test that response_params includes nextCursor"""
        paginator = HogQLCursorPaginator(limit=5, order_field="start_time", order_direction="DESC")
        paginator.results = [{"session_id": f"s{i}", "start_time": f"2025-01-06 {10 - i}:00:00"} for i in range(5)]
        paginator.response = MagicMock()
        paginator.response.results = [*paginator.results, {"extra": "item"}]

        params = paginator.response_params()

        assert "nextCursor" in params
        assert "hasMore" in params
        assert "limit" in params
        assert params["hasMore"]
        assert params["nextCursor"] is not None

    def test_from_limit_context_with_field_indices(self):
        """Test from_limit_context factory method passes field_indices correctly"""
        field_indices = {"session_id": 0, "start_time": 3}
        paginator = HogQLCursorPaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=5,
            order_field="start_time",
            order_direction="DESC",
            field_indices=field_indices,
        )

        assert paginator.field_indices == field_indices
        assert paginator.order_field == "start_time"
