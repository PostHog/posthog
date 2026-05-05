"""Strip-migration tests for the eval-report agent's heavy-prop tools.

`sample_generation_details`, `get_generation_detail`, and
`get_generation_text_repr` are the three tools that read heavy columns. They
route through `_execute_hogql_via_ai_events` which wraps the resolver. The
other query sites in `tools.py` deliberately stay on `events` directly via
`_execute_hogql` (see the module docstring on `_execute_hogql` for the
rationale).
"""

from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportContent
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import (
    get_generation_detail,
    get_generation_text_repr,
    sample_generation_details,
)

_VALID_GEN_ID = "12345678-1234-1234-1234-123456789abc"
_VALID_GEN_ID_2 = "abcdefab-cdef-abcd-efab-cdefabcdefab"

_sample_fn = sample_generation_details.func  # type: ignore[attr-defined]
_get_detail_fn = get_generation_detail.func  # type: ignore[attr-defined]
_get_text_repr_fn = get_generation_text_repr.func  # type: ignore[attr-defined]

_RESOLVE_PATH = "posthog.hogql_queries.ai.trace_id_resolver.resolve_trace_ids_for_generation_uuids"


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
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_routes_through_resolver_against_ai_events(self, _mock_lookup, mock_resolver):
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
        placeholders = kwargs["placeholders"]
        assert "trace_ids" in placeholders
        trace_id_values = [const.value for const in placeholders["trace_ids"].exprs]
        assert trace_id_values == ["trace-1"]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={})
    def test_skips_heavy_fetch_when_no_trace_ids_resolved(self, _mock_lookup, mock_resolver):
        """If the events preflight finds no rows (uuids purged or never existed),
        skip the heavy ai_events query entirely — no point fanning out across
        shards for a known-empty result."""
        result = _sample_fn(state=_state(self.team.id), generation_ids=[_VALID_GEN_ID])

        assert result == "[]"
        assert mock_resolver.call_count == 0


class TestGetGenerationDetailRoutesThroughResolver(BaseTest):
    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch("posthog.hogql.query.execute_hogql_query")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_main_query_uses_resolver_eval_query_uses_events(self, _mock_lookup, mock_events, mock_resolver):
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
        # Heavy fetch carries the resolved trace_id — proves the two-query
        # pattern wires through, not just that the WHERE has uuid.
        kwargs = mock_resolver.call_args.kwargs
        placeholders = kwargs["placeholders"]
        assert "trace_id" in placeholders
        assert placeholders["trace_id"].value == "trace-1"

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={})
    def test_returns_not_found_when_trace_id_lookup_misses(self, _mock_lookup, mock_resolver):
        """If the events preflight can't find the generation, surface a not-found
        error to the agent without paying for a heavy ai_events fan-out."""
        result = _get_detail_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "not found" in result.lower()
        assert mock_resolver.call_count == 0

    def test_invalid_generation_id_returns_error_without_querying(self):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            result = _get_detail_fn(state=_state(self.team.id), generation_id="not-a-uuid")
            assert "error" in result.lower()
            assert mock_resolver.call_count == 0


class TestGetGenerationTextReprRoutesThroughResolver(BaseTest):
    """`get_generation_text_repr` reads `$ai_input`/`$ai_output`/`$ai_output_choices`/
    `$ai_tools` indirectly through the formatter. Those are 4 of the 6 stripped
    heavy columns, so the tool must hit ai_events — querying `events.properties`
    directly would render an empty skeleton post-cutover."""

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_routes_through_resolver_against_ai_events(self, _mock_lookup, mock_resolver):
        """Heavy fetch goes through the resolver and selects from posthog.ai_events."""
        from datetime import datetime

        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "$ai_generation",
                    datetime(2026, 4, 27, 7, 0),
                    '[{"role":"user","content":"hi"}]',  # input
                    '"hello"',  # output (JSON-encoded string — text-output call shape)
                    None,  # output_choices
                    None,  # tools
                    0,  # is_error
                    None,  # error
                ]
            ]
        )

        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)

        # Sanity: rendered both input and output sections from heavy columns.
        assert "INPUT:" in result
        assert "OUTPUT:" in result
        assert "hi" in result
        assert "hello" in result

        assert mock_resolver.call_count == 1
        kwargs = mock_resolver.call_args.kwargs
        select = cast(ast.SelectQuery, kwargs["query"])
        from_chain = select.select_from.table.chain  # type: ignore[union-attr]
        # nosemgrep: hogql-no-string-table-chain
        assert from_chain == ["posthog", "ai_events"]
        assert kwargs["query_type"] == "EvalReportAgent"
        placeholders = kwargs["placeholders"]
        assert placeholders["trace_id"].value == "trace-1"
        assert placeholders["generation_id"].value == _VALID_GEN_ID

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_parses_output_choices_dict_format(self, _mock_lookup, mock_resolver):
        """`$ai_output_choices` must arrive as a parsed structure — the formatter's
        `isinstance(..., dict)` / `isinstance(..., list)` checks reject raw JSON
        strings, so the choices wouldn't render."""
        from datetime import datetime

        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "$ai_generation",
                    datetime(2026, 4, 27, 7, 0),
                    '[{"role":"user","content":"hi"}]',
                    "",  # empty output (chat-format calls)
                    '[{"message":{"role":"assistant","content":"choice content"}}]',
                    None,
                    0,
                    None,
                ]
            ]
        )

        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "choice content" in result

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_renders_error_section_when_is_error(self, _mock_lookup, mock_resolver):
        """`is_error` / `error` are dedicated columns — propagate them as
        `$ai_is_error` / `$ai_error` on the synthetic props so the formatter's
        error section fires."""
        from datetime import datetime

        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "$ai_generation",
                    datetime(2026, 4, 27, 7, 0),
                    '[{"role":"user","content":"hi"}]',
                    None,
                    None,
                    None,
                    1,  # is_error
                    "boom",  # error
                ]
            ]
        )

        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "ERROR:" in result
        assert "boom" in result

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_handles_all_heavy_columns_null(self, _mock_lookup, mock_resolver):
        """A generation with all heavy columns nulled should still render — the
        formatter just produces an empty body, no exception."""
        from datetime import datetime

        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "$ai_generation",
                    datetime(2026, 4, 27, 7, 0),
                    None,
                    None,
                    None,
                    None,
                    0,
                    None,
                ]
            ]
        )

        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        # No INPUT / OUTPUT / TOOLS / ERROR sections — formatter returns empty string.
        assert "INPUT:" not in result
        assert "OUTPUT:" not in result
        assert "ERROR:" not in result

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_passes_non_json_string_input_through_to_formatter(self, _mock_lookup, mock_resolver):
        """Heavy columns are usually JSON-encoded but a plain text input
        (embedding-style instrumentation) should still render — fall back to
        passing the raw string when JSON decoding fails."""
        from datetime import datetime

        mock_resolver.return_value = _resolver_response(
            [
                [
                    _VALID_GEN_ID,
                    "$ai_generation",
                    datetime(2026, 4, 27, 7, 0),
                    "plain text prompt",  # not valid JSON
                    None,
                    None,
                    None,
                    0,
                    None,
                ]
            ]
        )

        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "plain text prompt" in result

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={})
    def test_returns_not_found_when_trace_id_lookup_misses(self, _mock_lookup, mock_resolver):
        """Skip the heavy fan-out when the events preflight can't find the uuid."""
        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "not found" in result.lower()
        assert mock_resolver.call_count == 0

    @patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback")
    @patch(_RESOLVE_PATH, return_value={_VALID_GEN_ID: "trace-1"})
    def test_returns_not_found_when_ai_events_query_empty(self, _mock_lookup, mock_resolver):
        """Trace_id resolved but ai_events returns no rows (e.g. raced TTL eviction)."""
        mock_resolver.return_value = _resolver_response([])
        result = _get_text_repr_fn(state=_state(self.team.id), generation_id=_VALID_GEN_ID)
        assert "not found" in result.lower()

    def test_invalid_generation_id_returns_error_without_querying(self):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            with patch(_RESOLVE_PATH) as mock_lookup:
                result = _get_text_repr_fn(state=_state(self.team.id), generation_id="not-a-uuid")
                assert "error" in result.lower()
                assert mock_resolver.call_count == 0
                assert mock_lookup.call_count == 0
