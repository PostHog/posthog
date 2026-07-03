from datetime import UTC, datetime
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status


class TestOfflineEvaluationItemsEndpoint(APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/offline_evaluations/experiment_items/"

    def _make_response(self, rows: list[list[Any]]) -> MagicMock:
        response = MagicMock()
        response.results = rows
        return response

    def _preflight_row(
        self,
        item_id: str = "item-1",
        experiment_item_name: str | None = "case A",
        experiment_name: str | None = "exp-name",
        metric_name: str = "accuracy",
        metric_version: str = "1",
        eval_status: str | None = "completed",
        score: Any = 0.9,
        score_min: Any = 0.0,
        score_max: Any = 1.0,
        result_type: str | None = "numeric",
        reasoning: str | None = "looks good",
        trace_id: str | None = "trace-1",
        target_id: str | None = "trace-1",
        target_type: str | None = "trace_id",
        dataset_id: str | None = "ds-1",
        dataset_item_id: str | None = "ds-item-1",
        ai_expected: str | None = "expected",
        last_seen_at: Any = "2026-04-27T07:00:00+00:00",
        first_seen_at: Any = "2026-04-27T06:50:00+00:00",
    ) -> list[Any]:
        return [
            item_id,
            experiment_item_name,
            experiment_name,
            metric_name,
            metric_version,
            eval_status,
            score,
            score_min,
            score_max,
            result_type,
            reasoning,
            trace_id,
            target_id,
            target_type,
            dataset_id,
            dataset_item_id,
            ai_expected,
            last_seen_at,
            first_seen_at,
        ]

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_missing_experiment_id_returns_400(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        response = self.client.post(self.URL, {}, content_type="application/json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_preflight.call_count == 0
        assert mock_heavy.call_count == 0

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_empty_experiment_id_returns_400(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        response = self.client.post(self.URL, {"experiment_id": ""}, content_type="application/json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_preflight.call_count == 0
        assert mock_heavy.call_count == 0

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_returns_rows_in_20_column_tuple_order(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    item_id="item-1",
                    trace_id="trace-1",
                    last_seen_at="2026-04-27T07:00:00+00:00",
                    first_seen_at="2026-04-27T06:50:00+00:00",
                ),
            ]
        )
        mock_heavy.return_value = self._make_response(
            [["trace-1", '[{"role":"user","content":"hi"}]', '[{"role":"assistant","content":"hi"}]']]
        )

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {
            "results": [
                [
                    "item-1",
                    "case A",
                    "exp-name",
                    "accuracy",
                    "1",
                    "completed",
                    0.9,
                    0.0,
                    1.0,
                    "numeric",
                    "looks good",
                    "trace-1",
                    "ds-1",
                    "ds-item-1",
                    '[{"role":"user","content":"hi"}]',
                    '[{"role":"assistant","content":"hi"}]',
                    "expected",
                    "2026-04-27T07:00:00+00:00",
                    "trace-1",
                    "trace_id",
                ]
            ]
        }
        assert mock_preflight.call_args.kwargs["query_type"] == "LLMOfflineEvaluationItemsResolve"
        assert mock_heavy.call_args.kwargs["query_type"] == "LLMOfflineEvaluationItems"

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_empty_preflight_skips_heavy_query(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response([])

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        assert mock_heavy.call_count == 0

    @parameterized.expand(
        [
            ("blank_string", ""),
            ("none", None),
        ]
    )
    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_blank_only_trace_ids_short_circuit_heavy(
        self, _name: str, blank_value: Any, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        mock_preflight.return_value = self._make_response([self._preflight_row(item_id="item-1", trace_id=blank_value)])

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0][14] is None
        assert body["results"][0][15] is None
        assert mock_heavy.call_count == 0

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_preflight_failure_returns_500(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert mock_heavy.call_count == 0

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_heavy_failure_returns_500(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response([self._preflight_row()])
        mock_heavy.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_preflight_targets_events_and_heavy_targets_ai_events(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        from posthog.hogql import ast

        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    item_id="item-1",
                    trace_id="trace-1",
                    last_seen_at=datetime(2026, 4, 27, 7, 0, tzinfo=UTC),
                    first_seen_at=datetime(2026, 4, 27, 6, 50, tzinfo=UTC),
                ),
                self._preflight_row(
                    item_id="item-2",
                    trace_id="trace-2",
                    last_seen_at=datetime(2026, 4, 27, 6, 30, tzinfo=UTC),
                    first_seen_at=datetime(2026, 4, 27, 6, 0, tzinfo=UTC),
                ),
            ]
        )
        mock_heavy.return_value = self._make_response(
            [
                ["trace-1", '[{"role":"user","content":"hi"}]', '[{"role":"assistant","content":"hi"}]'],
                ["trace-2", '[{"role":"user","content":"hello"}]', '[{"role":"assistant","content":"hello"}]'],
            ]
        )

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK

        preflight_query = mock_preflight.call_args.kwargs["query"]
        preflight_select = cast(ast.SelectQuery, preflight_query)
        # nosemgrep: hogql-no-string-table-chain
        assert preflight_select.select_from.table.chain == ["events"]  # type: ignore[union-attr]

        heavy_query = mock_heavy.call_args.kwargs["query"]
        heavy_select = cast(ast.SelectQuery, heavy_query)
        # nosemgrep: hogql-no-string-table-chain
        assert heavy_select.select_from.table.chain == ["posthog", "ai_events"]  # type: ignore[union-attr]

        heavy_placeholders = mock_heavy.call_args.kwargs["placeholders"]
        trace_id_values = [c.value for c in heavy_placeholders["trace_ids"].exprs]
        assert trace_id_values == ["trace-1", "trace-2"]
        assert heavy_placeholders["ts_start"].value == datetime(2026, 4, 27, 6, 0, tzinfo=UTC)
        assert heavy_placeholders["ts_end"].value == datetime(2026, 4, 27, 7, 0, tzinfo=UTC)

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_traces_without_heavy_match_get_null_input_output(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(item_id="item-1", trace_id="trace-1"),
                self._preflight_row(item_id="item-2", trace_id="trace-2"),
            ]
        )
        mock_heavy.return_value = self._make_response(
            [["trace-1", '[{"role":"user","content":"hi"}]', '[{"role":"assistant","content":"hi"}]']]
        )

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["results"]) == 2
        assert body["results"][0][14] == '[{"role":"user","content":"hi"}]'
        assert body["results"][0][15] == '[{"role":"assistant","content":"hi"}]'
        assert body["results"][1][14] is None
        assert body["results"][1][15] is None

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_omitted_dates_inline_as_null_guards(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        mock_preflight.return_value = self._make_response([])

        response = self.client.post(
            self.URL,
            {"experiment_id": "exp-1"},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert mock_preflight.call_args.kwargs["placeholders"] == {}

        query = mock_preflight.call_args.kwargs["query"]
        true_constants: list[ast.Constant] = []

        class _BoolCounter(TraversingVisitor):
            def visit_constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, bool) and node.value is True:
                    true_constants.append(node)
                super().visit_constant(node)

        _BoolCounter().visit(query)
        assert len(true_constants) >= 2

    @patch("products.ai_observability.backend.api.offline_evaluations.query_ai_events")
    @patch("products.ai_observability.backend.api.offline_evaluations.execute_hogql_query")
    def test_provided_dates_are_inlined_into_query(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        from posthog.hogql import ast
        from posthog.hogql.visitor import TraversingVisitor

        mock_preflight.return_value = self._make_response([])

        response = self.client.post(
            self.URL,
            {
                "experiment_id": "exp-1",
                "date_from": "2026-04-01T00:00:00Z",
                "date_to": "2026-04-30T00:00:00Z",
            },
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert mock_preflight.call_args.kwargs["placeholders"] == {}

        query = mock_preflight.call_args.kwargs["query"]
        string_constants: list[str] = []

        class _StringCollector(TraversingVisitor):
            def visit_constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, str):
                    string_constants.append(node.value)
                super().visit_constant(node)

        _StringCollector().visit(query)
        assert "exp-1" in string_constants
        assert "2026-04-01T00:00:00Z" in string_constants
        assert "2026-04-30T00:00:00Z" in string_constants
