import pytest
from unittest.mock import Mock, patch

from posthog.hogql import ast

from posthog.errors import CHQueryErrorUnknownTable
from posthog.hogql_queries.ai.ai_table_resolver import (
    AIEventsExpiredError,
    AIEventsNotFoundError,
    is_ai_events_disabled,
    query_ai_events,
)


class TestIsAiEventsDisabled:
    @patch("posthog.hogql_queries.ai.ai_table_resolver.feature_enabled_or_false", return_value=True)
    def test_returns_true_when_killswitch_enabled(self, mock_flag):
        team = Mock(id=123, organization_id="org_abc")
        assert is_ai_events_disabled(team) is True
        mock_flag.assert_called_once_with(
            "ai-events-table-killswitch",
            "123",
            groups={"organization": "org_abc"},
            group_properties={"organization": {"id": "org_abc"}},
            send_feature_flag_events=False,
        )

    @patch("posthog.hogql_queries.ai.ai_table_resolver.feature_enabled_or_false", return_value=False)
    def test_returns_false_when_killswitch_disabled(self, mock_flag):
        team = Mock(id=456, organization_id="org_xyz")
        assert is_ai_events_disabled(team) is False
        mock_flag.assert_called_once_with(
            "ai-events-table-killswitch",
            "456",
            groups={"organization": "org_xyz"},
            group_properties={"organization": {"id": "org_xyz"}},
            send_feature_flag_events=False,
        )


class TestQueryAiEvents:
    @pytest.fixture(autouse=True)
    def _killswitch_off(self):
        # Default the kill switch off so existing paths don't depend on the flag boundary.
        with patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_disabled", return_value=False):
            yield

    def _make_query(self):
        return ast.SelectQuery(
            select=[ast.Field(chain=["trace_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", "ai_events"]), alias="ai_events"),
            where=ast.Constant(value=True),
        )

    def _make_result(self, results):
        return Mock(results=results)

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_returns_ai_events_result_when_data_found(self, mock_execute):
        ai_result = self._make_result([["trace-1"]])
        mock_execute.return_value = ai_result

        team = Mock(id=1, organization_id="org")
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
        )

        assert result is ai_result
        assert mock_execute.call_count == 1

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_falls_back_to_events_when_ai_events_empty(self, mock_execute):
        ai_result = self._make_result([])
        events_result = self._make_result([["trace-1"]])
        mock_execute.side_effect = [ai_result, events_result]

        team = Mock(id=1, organization_id="org")
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        assert result is events_result
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_raises_expired_when_ai_events_empty_but_events_has_rows(self, mock_execute):
        # ai_events empty, events probe finds the row -> the data aged past the TTL.
        mock_execute.side_effect = [self._make_result([]), self._make_result([[1]])]

        team = Mock(id=1, organization_id="org")
        with pytest.raises(AIEventsExpiredError):
            query_ai_events(
                query=self._make_query(),
                placeholders={},
                team=team,
                query_type="TestQuery",
            )
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_raises_not_found_when_empty_in_both_tables(self, mock_execute):
        mock_execute.side_effect = [self._make_result([]), self._make_result([])]

        team = Mock(id=1, organization_id="org")
        with pytest.raises(AIEventsNotFoundError):
            query_ai_events(
                query=self._make_query(),
                placeholders={},
                team=team,
                query_type="TestQuery",
            )
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_placeholders_for_ai_events(self, mock_execute):
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        placeholder = ast.Field(chain=["properties", "$ai_trace_id"])
        query_ai_events(
            query=self._make_query(),
            placeholders={"condition": placeholder},
            team=team,
            query_type="TestQuery",
        )

        # The placeholder should have been rewritten from properties.$ai_trace_id to trace_id
        actual_placeholders = mock_execute.call_args.kwargs.get("placeholders", {})
        rewritten = actual_placeholders["condition"]
        assert isinstance(rewritten, ast.Field)
        assert rewritten.chain == ["trace_id"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_placeholders_for_events_fallback(self, mock_execute):
        mock_execute.side_effect = [self._make_result([]), self._make_result([["found"]])]

        team = Mock(id=1, organization_id="org")
        # Use a native ai_events column name in the placeholder
        placeholder = ast.Field(chain=["trace_id"])
        query_ai_events(
            query=self._make_query(),
            placeholders={"condition": placeholder},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        # The events-table call should rewrite trace_id back to properties.$ai_trace_id
        actual_placeholders = mock_execute.call_args.kwargs.get("placeholders", {})
        rewritten = actual_placeholders["condition"]
        assert isinstance(rewritten, ast.Field)
        assert rewritten.chain == ["properties", "$ai_trace_id"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_rewrites_query_from_clause_for_events_fallback(self, mock_execute):
        mock_execute.side_effect = [self._make_result([]), self._make_result([])]

        team = Mock(id=1, organization_id="org")
        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        # The events-table call's FROM clause should have been rewritten to events
        actual_query = mock_execute.call_args.kwargs.get("query")
        assert isinstance(actual_query, ast.SelectQuery)
        assert actual_query.select_from is not None
        assert isinstance(actual_query.select_from.table, ast.Field)
        assert actual_query.select_from.table.chain == ["events"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_passes_optional_kwargs(self, mock_execute):
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        timings = Mock()
        modifiers = Mock()
        limit_context = Mock()
        settings = Mock()
        workload = Mock()

        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            settings=settings,
            workload=workload,
        )

        kwargs = mock_execute.call_args.kwargs
        assert kwargs["timings"] is timings
        assert kwargs["modifiers"] is modifiers
        assert kwargs["limit_context"] is limit_context
        assert kwargs["settings"] is settings
        assert kwargs["workload"] is workload

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_omits_unset_optional_kwargs(self, mock_execute):
        # Unset kwargs must NOT appear in the forwarded call so they don't override
        # execute_hogql_query's defaults (workload=DEFAULT, etc).
        mock_execute.return_value = self._make_result([["found"]])

        team = Mock(id=1, organization_id="org")
        query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
        )

        kwargs = mock_execute.call_args.kwargs
        assert "timings" not in kwargs
        assert "modifiers" not in kwargs
        assert "limit_context" not in kwargs
        assert "settings" not in kwargs
        assert "workload" not in kwargs

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_falls_back_to_events_when_ai_events_table_missing(self, mock_execute):
        # The satellite shard isn't provisioned -> ClickHouse raises UNKNOWN_TABLE. The
        # read path must fall back to events instead of surfacing the raw error.
        events_result = self._make_result([["trace-1"]])
        mock_execute.side_effect = [
            CHQueryErrorUnknownTable("There is no table posthog.sharded_ai_events", code=60),
            events_result,
        ]

        team = Mock(id=1, organization_id="org")
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        assert result is events_result
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_missing_table_without_fallback_classifies_via_events_probe(self, mock_execute):
        # Even without fall_back_to_events, a missing table must not surface a raw
        # ServerException — it degrades to the retention probe and a handled error.
        mock_execute.side_effect = [
            CHQueryErrorUnknownTable("There is no table posthog.sharded_ai_events", code=60),
            self._make_result([]),
        ]

        team = Mock(id=1, organization_id="org")
        with pytest.raises(AIEventsNotFoundError):
            query_ai_events(
                query=self._make_query(),
                placeholders={},
                team=team,
                query_type="TestQuery",
            )
        assert mock_execute.call_count == 2

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_disabled", return_value=True)
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_hogql_query")
    def test_killswitch_skips_ai_events_for_read_paths(self, mock_execute, _mock_disabled):
        # With the kill switch flipped, a read-path caller must serve from events without
        # ever touching the ai_events table.
        events_result = self._make_result([["trace-1"]])
        mock_execute.return_value = events_result

        team = Mock(id=1, organization_id="org")
        result = query_ai_events(
            query=self._make_query(),
            placeholders={},
            team=team,
            query_type="TestQuery",
            fall_back_to_events=True,
        )

        assert result is events_result
        assert mock_execute.call_count == 1
        # The single call must target the events table, not ai_events.
        actual_query = mock_execute.call_args.kwargs.get("query")
        assert actual_query.select_from.table.chain == ["events"]
