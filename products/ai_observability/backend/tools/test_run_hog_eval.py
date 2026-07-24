import json
import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from pydantic import ValidationError

from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES

from products.ai_observability.backend.tools.run_hog_eval import RunHogEvalTestArgs, RunHogEvalTestTool

EVENT_TIMESTAMP = "2026-07-20T12:34:56Z"


def _make_event(
    ai_input=None,
    ai_output_choices=None,
    event_type="$ai_generation",
):
    if ai_input is None:
        ai_input = [{"role": "user", "content": "Hello"}]
    if ai_output_choices is None:
        ai_output_choices = [{"message": {"role": "assistant", "content": "Hi there!"}}]
    return [
        str(uuid.uuid4()),
        event_type,
        json.dumps(
            {
                "$ai_input": ai_input,
                "$ai_output_choices": ai_output_choices,
                "$ai_model": "gpt-4",
            }
        ),
        "test-user",
        EVENT_TIMESTAMP,
        *(None,) * len(HEAVY_COLUMN_NAMES),
    ]


def _run_tool(tool, **kwargs):
    return async_to_sync(tool._arun_impl)(**kwargs)


def test_run_hog_eval_args_reject_unknown_target():
    with pytest.raises(ValidationError):
        RunHogEvalTestArgs(source="return true", target="traces")


class TestRunHogEvalTestTool(BaseTest):
    def _make_tool(self):
        return RunHogEvalTestTool(team=self.team, user=self.user)

    @parameterized.expand(
        [
            ("valid_return_true", "return true;", True),
            ("valid_return_false", "return false;", False),
            ("with_print", "print('checking'); return true;", True),
            ("length_check", "return length(output) > 0;", True),
            (
                "shared_timestamp",
                f"return evaluation_events.1.timestamp == '{EVENT_TIMESTAMP}';",
                True,
            ),
        ]
    )
    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_compilation_and_execution(self, _name, source, expected_verdict, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source=source, sample_count=1)

        assert artifact is None
        if expected_verdict:
            assert "PASS" in result
        else:
            assert "FAIL" in result

    def test_compilation_error(self):
        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="this is not valid hog {{{{", sample_count=1)

        assert "Compilation error" in result
        assert artifact is None

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_no_events_found(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = []
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=3)

        assert "No recent AI events" in result
        assert artifact is None

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_runtime_error_handling(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return properties.nonexistent.nested;", sample_count=1)

        assert artifact is None
        assert "Event" in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_result_formatting_includes_previews(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [
            _make_event(
                ai_input=[{"role": "user", "content": "What is PostHog?"}],
                ai_output_choices=[{"message": {"role": "assistant", "content": "PostHog is analytics."}}],
            )
        ]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=1)

        assert "Input:" in result
        assert "Output:" in result
        assert "Result: PASS" in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_null_return_shows_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return null;", sample_count=1)

        assert artifact is None
        assert "N/A" in result
        assert "ERROR" not in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_runtime_error_shows_error_not_na(self, mock_query):
        mock_response = MagicMock()
        mock_response.results = [_make_event()]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return 42;", sample_count=1)

        assert artifact is None
        assert "Result: ERROR" in result
        assert "Result: N/A" not in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_ai_metric_event_type(self, mock_query):
        mock_response = MagicMock()
        event_row = [
            str(uuid.uuid4()),
            "$ai_metric",
            json.dumps({"$ai_input_state": "some input", "$ai_output_state": "some output"}),
            "test-user",
            EVENT_TIMESTAMP,
        ]
        mock_response.results = [event_row]
        mock_query.return_value = mock_response

        tool = self._make_tool()
        result, artifact = _run_tool(tool, source="return true;", sample_count=1)

        assert "PASS" in result
        assert "$ai_metric" in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_heavy_column_remerge_from_ai_events(self, mock_query):
        """On the shared `events` table `properties.$ai_input` is empty, but the
        dedicated `ai_events` table carries the value in the native `input`
        column. The tool must re-merge those native columns back into
        `properties` so the Hog body can read `properties.$ai_input`. This test
        simulates the ai_events row shape coming back from the resolver."""
        from posthog.hogql_queries.ai.utils import HEAVY_COLUMN_NAMES

        # row[2]: stripped properties (no $ai_input).
        # row[5..10]: native heavy column values, in HEAVY_COLUMN_NAMES order
        #   ("input", "output", "output_choices", "input_state", "output_state", "tools").
        stripped_props = json.dumps({"$ai_model": "gpt-4o"})
        heavy_input = '[{"role":"user","content":"recovered from native column"}]'
        row = [
            str(uuid.uuid4()),
            "$ai_generation",
            stripped_props,
            "test-user",
            EVENT_TIMESTAMP,
            heavy_input,  # input
            None,  # output
            None,  # output_choices
            None,  # input_state
            None,  # output_state
            None,  # tools
        ]
        # Sanity: row layout matches what the source expects.
        assert len(row) == 5 + len(HEAVY_COLUMN_NAMES)
        mock_query.return_value = MagicMock(results=[row])

        tool = self._make_tool()
        # Hog body reads `properties.$ai_input` — this must be populated post-merge.
        result, _artifact = _run_tool(
            tool,
            source="return properties.$ai_input != null;",
            sample_count=1,
        )

        assert "Result: PASS" in result, f"expected PASS after heavy-merge, got: {result}"

    @patch("posthog.temporal.ai_observability.run_trace_evaluation.run_hog_eval_over_recent_traces")
    def test_trace_target_evaluates_whole_traces(self, mock_run_over_traces):
        from posthog.temporal.ai_observability.run_trace_evaluation import TraceHogTestResult

        mock_run_over_traces.return_value = [
            TraceHogTestResult(
                trace_id="trace-1",
                verdict=True,
                reasoning="looks good",
                error=None,
                input_preview="hello",
                output_preview="world",
            )
        ]

        tool = self._make_tool()
        result, artifact = _run_tool(
            tool,
            source="return target.type == 'trace';",
            sample_count=2,
            target="trace",
            window_seconds=120,
        )

        assert artifact is None
        assert mock_run_over_traces.call_args.kwargs["window_seconds"] == 120
        assert "Trace trace-1" in result
        assert "Result: PASS" in result

    @patch("products.ai_observability.backend.tools.run_hog_eval.query_ai_events")
    def test_query_targets_ai_events(self, mock_query):
        """The constructed SelectQuery must target `posthog.ai_events` — otherwise
        the heavy column slots in the projection are NULL on the events table."""
        from posthog.hogql import ast

        mock_query.return_value = MagicMock(results=[])
        tool = self._make_tool()
        _run_tool(tool, source="return true;", sample_count=1)

        kwargs = mock_query.call_args.kwargs
        select = kwargs["query"]
        assert isinstance(select, ast.SelectQuery)
        from_chain = select.select_from.table.chain  # type: ignore[union-attr]
        # nosemgrep: hogql-no-string-table-chain
        assert from_chain == ["posthog", "ai_events"]
