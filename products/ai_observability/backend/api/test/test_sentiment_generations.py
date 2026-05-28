from datetime import UTC, datetime
from typing import Any, cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status


class TestSentimentGenerationsEndpoint(APIBaseTest):
    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/sentiment/generations/"

    def _make_response(self, rows: list[list[Any]]) -> MagicMock:
        response = MagicMock()
        response.results = rows
        return response

    def _preflight_row(
        self,
        uuid: str = "uuid-1",
        trace_id: str = "trace-1",
        model: str = "gpt-4",
        distinct_id: str = "person-1",
        ts_max: Any = "2026-04-27T07:00:00+00:00",
        ts_min: Any = "2026-04-27T06:50:00+00:00",
    ) -> list[Any]:
        return [uuid, trace_id, model, distinct_id, ts_max, ts_min]

    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_returns_rows_in_tuple_order(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    uuid="uuid-1",
                    trace_id="trace-1",
                    model="gpt-4",
                    distinct_id="person-1",
                    ts_max="2026-04-27T07:00:00+00:00",
                    ts_min="2026-04-27T06:50:00+00:00",
                ),
            ]
        )
        mock_heavy.return_value = self._make_response([["trace-1", '[{"role":"user","content":"hi"}]']])

        response = self.client.post(
            self.URL,
            {"filters": {"dateRange": {"date_from": "-7d", "date_to": None}, "properties": []}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body == {
            "results": [
                [
                    "uuid-1",
                    "trace-1",
                    '[{"role":"user","content":"hi"}]',
                    "gpt-4",
                    "person-1",
                    "2026-04-27T07:00:00+00:00",
                    "2026-04-27T06:50:00+00:00",
                ]
            ]
        }
        assert mock_preflight.call_args.kwargs["query_type"] == "LLMSentimentGenerationsTraceIdResolve"
        assert mock_heavy.call_args.kwargs["query_type"] == "LLMSentimentGenerations"

    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_invalid_filters_returns_400(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        response = self.client.post(
            self.URL,
            {"filters": {"filterTestAccounts": "this should be a bool"}},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert mock_preflight.call_count == 0
        assert mock_heavy.call_count == 0

    @parameterized.expand(
        [
            ("missing_filters_key", {}),
            ("empty_filters_dict", {"filters": {}}),
        ]
    )
    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_empty_preflight_skips_heavy_query(
        self,
        _name: str,
        payload: dict[str, Any],
        mock_preflight: MagicMock,
        mock_heavy: MagicMock,
    ) -> None:
        mock_preflight.return_value = self._make_response([])

        response = self.client.post(self.URL, payload, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}
        assert mock_heavy.call_count == 0

    @parameterized.expand(
        [
            ("preflight", "preflight"),
            ("heavy", "heavy"),
        ]
    )
    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_clickhouse_failure_returns_500(
        self,
        _name: str,
        failing_stage: str,
        mock_preflight: MagicMock,
        mock_heavy: MagicMock,
    ) -> None:
        if failing_stage == "preflight":
            mock_preflight.side_effect = RuntimeError("clickhouse boom")
        else:
            mock_preflight.return_value = self._make_response([self._preflight_row()])
            mock_heavy.side_effect = RuntimeError("clickhouse boom")

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        if failing_stage == "preflight":
            assert mock_heavy.call_count == 0

    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_preflight_targets_events_and_heavy_targets_ai_events(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        from posthog.hogql import ast

        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(
                    uuid="uuid-1",
                    trace_id="trace-1",
                    ts_max=datetime(2026, 4, 27, 7, 0, tzinfo=UTC),
                    ts_min=datetime(2026, 4, 27, 6, 50, tzinfo=UTC),
                ),
                self._preflight_row(
                    uuid="uuid-2",
                    trace_id="trace-2",
                    ts_max=datetime(2026, 4, 27, 6, 30, tzinfo=UTC),
                    ts_min=datetime(2026, 4, 27, 6, 0, tzinfo=UTC),
                ),
            ]
        )
        mock_heavy.return_value = self._make_response(
            [
                ["trace-1", '[{"role":"user","content":"hi"}]'],
                ["trace-2", '[{"role":"user","content":"hello"}]'],
            ]
        )

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
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
        uuid_values = [c.value for c in heavy_placeholders["uuids"].exprs]
        assert trace_id_values == ["trace-1", "trace-2"]
        assert uuid_values == ["uuid-1", "uuid-2"]
        assert heavy_placeholders["ts_start"].value == datetime(2026, 4, 27, 6, 0, tzinfo=UTC)
        assert heavy_placeholders["ts_end"].value == datetime(2026, 4, 27, 7, 0, tzinfo=UTC)

    # The heavy SQL must carry an explicit `LIMIT` matching the preflight's
    # `GENERATIONS_QUERY_LIMIT`. Without it, `execute_hogql_query` (via
    # `LimitContext.QUERY`) injects a default of 100 rows and the `GROUP BY
    # trace_id` is silently truncated when the preflight returns more, so
    # the truncated half renders as blank cards on the Sentiment tab.
    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_heavy_query_has_explicit_limit(self, mock_preflight: MagicMock, mock_heavy: MagicMock) -> None:
        from posthog.hogql import ast as hogql_ast

        from products.ai_observability.backend.api.sentiment import GENERATIONS_QUERY_LIMIT

        mock_preflight.return_value = self._make_response([self._preflight_row()])
        mock_heavy.return_value = self._make_response([["trace-1", '[{"role":"user","content":"hi"}]']])

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK

        heavy_query = mock_heavy.call_args.kwargs["query"]
        heavy_select = cast(hogql_ast.SelectQuery, heavy_query)
        assert heavy_select.limit is not None, "heavy query must have an explicit LIMIT"
        assert isinstance(heavy_select.limit, hogql_ast.Constant)
        assert heavy_select.limit.value == GENERATIONS_QUERY_LIMIT

    # When the heavy table returns fewer rows than the preflight (e.g. a
    # trace had no input column, or partial ai_events coverage in some
    # future state), the un-matched traces fall back to null ai_input and
    # the response still includes them positionally. This keeps the
    # frontend dedup grouping (and the per-card "View trace" links)
    # working for the remaining rows.
    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    @patch("products.ai_observability.backend.api.sentiment.execute_hogql_query")
    def test_traces_without_heavy_match_get_null_ai_input(
        self, mock_preflight: MagicMock, mock_heavy: MagicMock
    ) -> None:
        mock_preflight.return_value = self._make_response(
            [
                self._preflight_row(uuid="uuid-1", trace_id="trace-1"),
                self._preflight_row(uuid="uuid-2", trace_id="trace-2"),
            ]
        )
        mock_heavy.return_value = self._make_response([["trace-1", '[{"role":"user","content":"hi"}]']])

        response = self.client.post(self.URL, {"filters": {}}, content_type="application/json")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["results"]) == 2
        assert body["results"][0][2] == '[{"role":"user","content":"hi"}]'
        assert body["results"][1][2] is None


class TestSentimentGenerationsRealClickhouse(ClickhouseTestMixin, APIBaseTest):
    """Regression coverage that exercises the real `replace_filters` + ClickHouse
    pipeline for the Sentiments-tab preflight, not the mocked path.

    Previously the preflight aliased `max(timestamp) AS timestamp`, which shadowed
    the `timestamp` column. `replace_filters` injects `toTimeZone(timestamp, '<tz>')`
    comparisons for any team whose `timezone` is not UTC, and HogQL bound that
    inner `timestamp` to the aggregate alias — surfacing as an "illegal aggregate
    in WHERE" 500 from ClickHouse. The frontend swallowed the 500 into an empty
    `results` array, rendering the "No generations with user input found" copy on
    the Sentiments tab even when valid `$ai_generation` events existed for the
    team. The mocked tests above never tripped this because they short-circuit
    `execute_hogql_query`.
    """

    URL: str = ""

    def setUp(self) -> None:
        super().setUp()
        self.URL = f"/api/environments/{self.team.id}/llm_analytics/sentiment/generations/"
        # Reproduce the customer config that triggered the bug — any non-UTC tz
        # is sufficient; `replace_filters` only wraps `timestamp` in `toTimeZone`
        # when the team timezone differs from UTC.
        self.team.timezone = "US/Eastern"
        self.team.save()

    @parameterized.expand(
        [
            ("no_events", False),
            ("with_event", True),
        ]
    )
    @patch("products.ai_observability.backend.api.sentiment.execute_with_ai_events_fallback")
    def test_preflight_against_real_clickhouse_for_non_utc_team(
        self,
        _name: str,
        seed_event: bool,
        mock_heavy: MagicMock,
    ) -> None:
        """Without the alias-shadow fix, the preflight 500s here regardless of data
        — the regression is in the SQL/`replace_filters` interaction, not in row
        retrieval. The `with_event` case additionally confirms end-to-end shape on
        a non-UTC team so a future refactor of the preflight can't silently drop
        rows for the affected timezone class."""
        if seed_event:
            _create_person(team_id=self.team.pk, distinct_ids=["person-1"])
            _create_event(
                event="$ai_generation",
                team=self.team,
                distinct_id="person-1",
                properties={
                    "$ai_trace_id": "trace-non-utc-1",
                    "$ai_model": "gpt-4",
                    "$ai_input": [{"role": "user", "content": "hi"}],
                },
            )
            mock_heavy.return_value = MagicMock(
                results=[("trace-non-utc-1", '[{"role":"user","content":"hi"}]')],
            )
        else:
            mock_heavy.return_value = MagicMock(results=[])

        response = self.client.post(
            self.URL,
            {"filters": {"dateRange": {"date_from": "-1d", "date_to": None}}},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        if seed_event:
            assert len(body["results"]) == 1
            # Response tuple positions: [uuid, trace_id, ai_input, model, distinct_id, ts_max, ts_min]
            assert body["results"][0][1] == "trace-non-utc-1"
            assert body["results"][0][3] == "gpt-4"
            assert body["results"][0][4] == "person-1"
        else:
            assert body == {"results": []}
            # Heavy query is skipped when preflight is empty — confirms the preflight
            # ran to completion (rather than crashing) and returned no rows.
            assert mock_heavy.call_count == 0
