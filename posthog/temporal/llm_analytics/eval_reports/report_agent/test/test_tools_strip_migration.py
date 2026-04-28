"""Strip-migration tests for the eval-report agent's heavy-prop tools.

`sample_generation_details` and `get_generation_detail` are the two tools
that read heavy columns. They route through `_execute_hogql_via_ai_events`
which wraps the resolver. The other 8 query sites in `tools.py` deliberately
stay on `events` directly via `_execute_hogql` (see the module docstring on
`_execute_hogql` for the rationale).
"""

from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportContent
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import (
    get_generation_detail,
    sample_generation_details,
)

_VALID_GEN_ID = "12345678-1234-1234-1234-123456789abc"
_VALID_GEN_ID_2 = "abcdefab-cdef-abcd-efab-cdefabcdefab"

_sample_fn = sample_generation_details.func  # type: ignore[attr-defined]
_get_detail_fn = get_generation_detail.func  # type: ignore[attr-defined]


def _state(team_id: int) -> dict:
    return {
        "team_id": team_id,
        "evaluation_id": "eval-1",
        "period_start": "2026-04-27T00:00:00+00:00",
        "period_end": "2026-04-28T00:00:00+00:00",
        "previous_period_start": "2026-04-26T00:00:00+00:00",
        "report": EvalReportContent(),
    }


def _resolver_response(rows: list[list]) -> MagicMock:
    response = MagicMock()
    response.results = rows
    return response


class TestSampleGenerationDetailsRoutesThroughResolver(BaseTest):
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    def test_routes_through_resolver_against_ai_events(self, mock_resolver):
        """The heavy-prop tool must hit the resolver, not raw `execute_hogql_query`."""
        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "gpt-4o",  # model
                    [{"role": "user", "content": "hi"}],  # input (heavy, native column)
                    [{"role": "assistant", "content": "hello"}],  # output
                    10,
                    5,
                    "trace-1",
                    False,
                    None,
                    None,
                    None,
                    None,
                    None,
                ]
            ]
        )

        result = _sample_fn(state=_state(self.team.id), generation_ids=[_VALID_GEN_ID])

        # Returns rendered JSON with input/output previews from heavy columns.
        assert "post-strip" not in result  # sanity: nothing weird leaked
        assert mock_resolver.call_count == 1
        kwargs = mock_resolver.call_args.kwargs
        select = cast(ast.SelectQuery, kwargs["query"])
        from_chain = select.select_from.table.chain  # type: ignore[union-attr]
        # nosemgrep: hogql-no-string-table-chain
        assert from_chain == ["posthog", "ai_events"]
        assert kwargs["query_type"] == "EvalReportAgent"


class TestGetGenerationDetailRoutesThroughResolver(BaseTest):
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch("posthog.hogql.query.execute_hogql_query")
    def test_main_query_uses_resolver_eval_query_uses_events(self, mock_events, mock_resolver):
        """Within `get_generation_detail`, the main generation lookup reads heavy
        columns and routes via the resolver. The eval-rows lookup reads only
        non-heavy fields (`$ai_evaluation_*`) and stays on `events` directly.
        """
        from datetime import datetime

        # Resolver returns the gen row (heavy path).
        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "gpt-4o",  # model
                    "openai",  # provider
                    [{"role": "user", "content": "hi"}],  # input
                    [{"role": "assistant", "content": "hello"}],  # output
                    10,
                    5,
                    0.001,
                    0.4,
                    "trace-1",
                    "https://api.openai.com/v1/",
                    datetime(2026, 4, 27, 7, 0),
                    False,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ]
            ]
        )
        # Non-resolver path returns eval rows.
        mock_events.return_value = MagicMock(results=[])

        _get_detail_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)

        # Heavy path went through the resolver.
        assert mock_resolver.call_count == 1
        # Non-heavy eval-rows query went through plain execute_hogql_query (events).
        assert mock_events.call_count == 1

    def test_invalid_generation_id_returns_error_without_querying(self):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            result = _get_detail_fn(state=_state(self.team.id), generation_id="not-a-uuid")
            assert "error" in result.lower()
            assert mock_resolver.call_count == 0
