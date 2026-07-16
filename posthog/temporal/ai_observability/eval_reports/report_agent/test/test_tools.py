"""Tests for the v2 eval report agent output tools (set_title, add_section, add_citation)."""

import json
import datetime as dt
from typing import NotRequired, TypedDict

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.temporal.ai_observability.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    Citation,
    EvalReportContent,
    ReportSection,
)
from posthog.temporal.ai_observability.eval_reports.report_agent.tools import (
    _UUID_RE,
    _ch_ts,
    _widened_ts_window,
    add_citation,
    add_section,
    get_eval_report_tools,
    get_report_run,
    get_summary_metrics,
    get_trace_detail,
    list_all_eval_results,
    list_recent_report_runs,
    sample_eval_results,
    sample_trace_details,
    set_title,
)

_VALID_GEN_ID = "12345678-1234-1234-1234-123456789abc"
_VALID_TRACE_ID = "abcdefab-cdef-abcd-efab-cdefabcdefab"

# LangChain @tool returns StructuredTool which has .func, but mypy types it as BaseTool
_set_title_fn = set_title.func  # type: ignore[attr-defined]
_add_section_fn = add_section.func  # type: ignore[attr-defined]
_add_citation_fn = add_citation.func  # type: ignore[attr-defined]
_list_recent_report_runs_fn = list_recent_report_runs.func  # type: ignore[attr-defined]
_get_report_run_fn = get_report_run.func  # type: ignore[attr-defined]
_get_summary_metrics_fn = get_summary_metrics.func  # type: ignore[attr-defined]
_list_all_eval_results_fn = list_all_eval_results.func  # type: ignore[attr-defined]
_sample_eval_results_fn = sample_eval_results.func  # type: ignore[attr-defined]
_sample_trace_details_fn = sample_trace_details.func  # type: ignore[attr-defined]
_get_trace_detail_fn = get_trace_detail.func  # type: ignore[attr-defined]


class _ReportToolState(TypedDict):
    report: EvalReportContent
    evaluation_target: NotRequired[str]
    team_id: NotRequired[int]
    evaluation_id: NotRequired[str]
    output_type: NotRequired[str]
    period_start: NotRequired[str]
    period_end: NotRequired[str]


def _state_with_empty_report(*, evaluation_target: str | None = None) -> _ReportToolState:
    state: _ReportToolState = {"report": EvalReportContent()}
    if evaluation_target is not None:
        state["evaluation_target"] = evaluation_target
    return state


def _trace_report_tool_state() -> _ReportToolState:
    return {
        "report": EvalReportContent(),
        "evaluation_target": "trace",
        "team_id": 7,
        "evaluation_id": "eval-id",
        "output_type": "boolean",
        "period_start": "2026-04-08T14:00:00+00:00",
        "period_end": "2026-04-08T15:00:00+00:00",
    }


class TestChTs(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "iso_with_tz",
                "2026-03-12T10:05:48.034000+00:00",
                dt.datetime(2026, 3, 12, 10, 5, 48, 34000, tzinfo=dt.UTC),
            ),
            ("iso_no_tz", "2026-03-12T10:05:48.034000", dt.datetime(2026, 3, 12, 10, 5, 48, 34000, tzinfo=dt.UTC)),
            ("iso_z_suffix", "2026-03-12T10:05:48.034000Z", dt.datetime(2026, 3, 12, 10, 5, 48, 34000, tzinfo=dt.UTC)),
            ("no_microseconds", "2026-03-12T10:05:48+00:00", dt.datetime(2026, 3, 12, 10, 5, 48, tzinfo=dt.UTC)),
            ("different_timezone", "2026-03-12T12:05:48+02:00", dt.datetime(2026, 3, 12, 10, 5, 48, tzinfo=dt.UTC)),
        ]
    )
    def test_converts_iso_to_utc_datetime(self, _name, iso_input, expected):
        result = _ch_ts(iso_input)
        self.assertEqual(result, expected)
        # Returning a datetime (not string) so HogQL serializes with correct TZ alignment.
        self.assertIsInstance(result, dt.datetime)
        self.assertEqual(result.tzinfo, dt.UTC)


class TestWidenedTsWindow(SimpleTestCase):
    def test_widens_start_by_7_days_and_end_by_1_day(self):
        state = {
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
        }
        ts_start, ts_end = _widened_ts_window(state)
        self.assertEqual(ts_start, dt.datetime(2026, 4, 1, 14, 0, tzinfo=dt.UTC))
        self.assertEqual(ts_end, dt.datetime(2026, 4, 9, 15, 0, tzinfo=dt.UTC))

    def test_falls_back_to_sentinels_on_missing_keys(self):
        ts_start, ts_end = _widened_ts_window({})
        # Wide sentinel bounds so a bad state doesn't prevent partition pruning
        self.assertEqual(ts_start.year, 2020)
        self.assertEqual(ts_end.year, 2099)

    def test_falls_back_on_malformed_timestamps(self):
        state = {"period_start": "not-a-timestamp", "period_end": "also-bad"}
        ts_start, ts_end = _widened_ts_window(state)
        self.assertEqual(ts_start.year, 2020)
        self.assertEqual(ts_end.year, 2099)


class TestSummaryMetrics(SimpleTestCase):
    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_boolean_keeps_pass_rate_separate_from_outcome_distribution(self, mock_execute_hogql):
        mock_execute_hogql.side_effect = [
            [[80, 18, 2, 100]],
            [[7, 2, 1, 10]],
        ]
        state = {
            "team_id": 1,
            "evaluation_id": "eval-id",
            "evaluation_target": "trace",
            "output_type": "boolean",
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
            "previous_period_start": "2026-04-08T13:00:00+00:00",
        }

        result = json.loads(_get_summary_metrics_fn(state=state))

        self.assertEqual(
            result["current_period"]["result_rates"],
            {"pass": 80.0, "fail": 18.0, "na": 2.0},
        )
        self.assertEqual(result["current_period"]["pass_rate"], 81.63)
        for call in mock_execute_hogql.call_args_list:
            self.assertIn("properties.$ai_target_type = 'trace_id'", call.args[1])

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_boolean_current_period_preserves_zero_pass_rate_when_no_results_are_applicable(self, mock_execute_hogql):
        mock_execute_hogql.side_effect = [
            [[0, 0, 4, 4]],
            [[0, 0, 3, 3]],
        ]
        state = {
            "team_id": 1,
            "evaluation_id": "eval-id",
            "output_type": "boolean",
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
            "previous_period_start": "2026-04-08T13:00:00+00:00",
        }

        result = json.loads(_get_summary_metrics_fn(state=state))

        self.assertEqual(result["current_period"]["pass_rate"], 0.0)
        self.assertIsNone(result["previous_period"]["pass_rate"])

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_sentiment_uses_label_predicates_and_returns_distribution(self, mock_execute_hogql):
        mock_execute_hogql.side_effect = [
            [[2, 1, 1, 4]],
            [[1, 1, 0, 2]],
        ]
        state = {
            "team_id": 1,
            "evaluation_id": "eval-id",
            "output_type": "sentiment",
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
            "previous_period_start": "2026-04-08T13:00:00+00:00",
        }

        result = json.loads(_get_summary_metrics_fn(state=state))

        self.assertEqual(result["output_type"], "sentiment")
        self.assertEqual(
            result["current_period"]["result_counts"],
            {"positive": 2, "neutral": 1, "negative": 1},
        )
        self.assertEqual(
            result["current_period"]["result_rates"],
            {"positive": 50.0, "neutral": 25.0, "negative": 25.0},
        )
        current_query = mock_execute_hogql.call_args_list[0].args[1]
        self.assertIn("properties.$ai_sentiment_label = 'positive'", current_query)
        self.assertIn("properties.$ai_evaluation_result_type = 'sentiment'", current_query)
        self.assertNotIn("properties.$ai_evaluation_result = true", current_query)


class TestTargetAwareEvalResults(SimpleTestCase):
    def _state(self, evaluation_target: str) -> dict:
        return {
            "team_id": 1,
            "evaluation_id": "eval-id",
            "evaluation_target": evaluation_target,
            "output_type": "boolean",
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
        }

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_sample_uses_new_target_id_with_legacy_fallback_and_target_specific_key(self, mock_execute_hogql):
        mock_execute_hogql.side_effect = [
            [[_VALID_GEN_ID, True, "useful", True, None]],
            [["customer-trace/42", False, "failed", True, None]],
        ]

        generation_result = json.loads(_sample_eval_results_fn(state=self._state("generation")))
        trace_result = json.loads(_sample_eval_results_fn(state=self._state("trace")))

        self.assertEqual(generation_result[0]["generation_id"], _VALID_GEN_ID)
        self.assertNotIn("trace_id", generation_result[0])
        self.assertEqual(trace_result[0]["trace_id"], "customer-trace/42")
        self.assertNotIn("generation_id", trace_result[0])
        for call in mock_execute_hogql.call_args_list:
            query = call.args[1]
            self.assertIn("properties.$ai_target_id", query)
            self.assertIn("properties.$ai_target_event_id", query)
        generation_query = mock_execute_hogql.call_args_list[0].args[1]
        trace_query = mock_execute_hogql.call_args_list[1].args[1]
        self.assertIn("isNull(properties.$ai_target_type)", generation_query)
        self.assertIn("properties.$ai_target_type = 'trace_id'", trace_query)

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_list_uses_unified_target_id_for_trace_results(self, mock_execute_hogql):
        mock_execute_hogql.side_effect = [
            [[1]],
            [["customer-trace/42", False, True, None, "failed criteria"]],
        ]

        result = _list_all_eval_results_fn(state=self._state("trace"))

        self.assertIn("customer-trace/42", result)
        query = mock_execute_hogql.call_args_list[1].args[1]
        self.assertIn("properties.$ai_target_id", query)
        self.assertIn("properties.$ai_target_event_id", query)


class TestTraceDetailTools(SimpleTestCase):
    def _state(self) -> dict:
        return {
            "team_id": 7,
            "evaluation_id": "eval-id",
            "evaluation_target": "trace",
            "output_type": "boolean",
            "period_start": "2026-04-08T14:00:00+00:00",
            "period_end": "2026-04-08T15:00:00+00:00",
        }

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._fetch_and_format_trace")
    def test_sample_accepts_evaluated_opaque_trace_ids_and_bounds_each_rendering(
        self, mock_fetch: MagicMock, mock_execute_hogql: MagicMock
    ) -> None:
        mock_fetch.return_value = MagicMock(text_repr="x" * 5_000, event_count=4)
        trace_id = " customer/trace:alpha 42 "
        mock_execute_hogql.return_value = [[trace_id]]

        result = json.loads(_sample_trace_details_fn(state=self._state(), trace_ids=[trace_id]))

        self.assertEqual(result[0]["trace_id"], trace_id)
        self.assertEqual(len(result[0]["text"]), 3_000)
        self.assertEqual(mock_fetch.call_args.kwargs["trace_id"], trace_id)
        self.assertEqual(mock_fetch.call_args.kwargs["max_length"], 3_000)
        self.assertEqual(mock_fetch.call_args.kwargs["window_start"], "2020-01-01T00:00:00+00:00")
        self.assertEqual(mock_fetch.call_args.kwargs["window_end"], "2099-01-01T00:00:00+00:00")
        authorization_query = mock_execute_hogql.call_args.args[1]
        self.assertIn("properties.$ai_evaluation_id = {evaluation_id}", authorization_query)
        self.assertIn("properties.$ai_target_type = 'trace_id'", authorization_query)
        self.assertIn("timestamp >= {ts_start}", authorization_query)
        self.assertIn("timestamp < {ts_end}", authorization_query)

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._fetch_and_format_trace")
    def test_deep_dive_rejects_trace_outside_evaluation_period(
        self, mock_fetch: MagicMock, mock_execute_hogql: MagicMock
    ) -> None:
        mock_execute_hogql.return_value = []

        result = json.loads(_get_trace_detail_fn(state=self._state(), trace_id="unrelated-trace"))

        self.assertEqual(
            result,
            {"trace_id": "unrelated-trace", "error": "Trace not found for this evaluation period"},
        )
        mock_fetch.assert_not_called()

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._fetch_and_format_trace")
    def test_deep_dive_rejects_oversized_trace_id_without_querying(
        self, mock_fetch: MagicMock, mock_execute_hogql: MagicMock
    ) -> None:
        result = json.loads(_get_trace_detail_fn(state=self._state(), trace_id="x" * 256))

        self.assertEqual(result, {"error": "Invalid trace ID"})
        mock_fetch.assert_not_called()
        mock_execute_hogql.assert_not_called()

    def test_target_specific_tool_sets_do_not_expose_irrelevant_detail_tools(self):
        generation_tools = {tool.name for tool in get_eval_report_tools("generation")}
        trace_tools = {tool.name for tool in get_eval_report_tools("trace")}

        self.assertIn("sample_generation_details", generation_tools)
        self.assertNotIn("sample_trace_details", generation_tools)
        self.assertIn("sample_trace_details", trace_tools)
        self.assertIn("get_trace_detail", trace_tools)
        self.assertNotIn("sample_generation_details", trace_tools)


class TestUuidRegex(SimpleTestCase):
    def test_matches_canonical_uuid(self):
        self.assertIsNotNone(_UUID_RE.fullmatch("12345678-1234-1234-1234-123456789abc"))

    def test_rejects_uppercase(self):
        # Our pattern is strict lowercase — matches the format PostHog emits.
        self.assertIsNone(_UUID_RE.fullmatch("12345678-1234-1234-1234-123456789ABC"))

    def test_rejects_too_short(self):
        self.assertIsNone(_UUID_RE.fullmatch("12345678-1234-1234-1234-123456789ab"))

    def test_rejects_extra_chars(self):
        self.assertIsNone(_UUID_RE.fullmatch("12345678-1234-1234-1234-123456789abc-extra"))


class TestSetTitle(SimpleTestCase):
    def test_sets_title_on_state(self):
        state = _state_with_empty_report()
        result = _set_title_fn(state=state, title="Pass rate steady at 94%")
        self.assertEqual(state["report"].title, "Pass rate steady at 94%")
        self.assertIn("Pass rate steady at 94%", result)

    def test_strips_whitespace(self):
        state = _state_with_empty_report()
        _set_title_fn(state=state, title="  padded title  ")
        self.assertEqual(state["report"].title, "padded title")

    def test_rejects_empty_title(self):
        state = _state_with_empty_report()
        result = _set_title_fn(state=state, title="")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].title, "")

    def test_rejects_whitespace_only_title(self):
        state = _state_with_empty_report()
        result = _set_title_fn(state=state, title="   ")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].title, "")

    def test_clips_very_long_title(self):
        state = _state_with_empty_report()
        long_title = "x" * 500
        _set_title_fn(state=state, title=long_title)
        self.assertLessEqual(len(state["report"].title), 200)
        self.assertTrue(state["report"].title.endswith("..."))


class TestAddSection(SimpleTestCase):
    def test_appends_section(self):
        state = _state_with_empty_report()
        result = _add_section_fn(state=state, title="Summary", content="Pass rate is 94%.")
        self.assertEqual(len(state["report"].sections), 1)
        self.assertEqual(state["report"].sections[0].title, "Summary")
        self.assertEqual(state["report"].sections[0].content, "Pass rate is 94%.")
        self.assertIn("Summary", result)

    def test_rejects_empty_title(self):
        state = _state_with_empty_report()
        result = _add_section_fn(state=state, title="", content="body")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].sections, [])

    def test_rejects_empty_content(self):
        state = _state_with_empty_report()
        result = _add_section_fn(state=state, title="Summary", content="")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].sections, [])

    def test_allows_up_to_max_sections(self):
        state = _state_with_empty_report()
        for i in range(MAX_REPORT_SECTIONS):
            result = _add_section_fn(state=state, title=f"Section {i}", content=f"Body {i}")
            self.assertNotIn("Error", result)
        self.assertEqual(len(state["report"].sections), MAX_REPORT_SECTIONS)

    def test_rejects_over_max_sections(self):
        state = _state_with_empty_report()
        # Fill to the max
        for i in range(MAX_REPORT_SECTIONS):
            _add_section_fn(state=state, title=f"Section {i}", content="body")
        # Next one should be rejected
        result = _add_section_fn(state=state, title="One too many", content="body")
        self.assertIn("Error", result)
        self.assertIn("maximum", result)
        self.assertEqual(len(state["report"].sections), MAX_REPORT_SECTIONS)

    def test_preserves_section_order(self):
        state = _state_with_empty_report()
        _add_section_fn(state=state, title="First", content="a")
        _add_section_fn(state=state, title="Second", content="b")
        _add_section_fn(state=state, title="Third", content="c")
        titles = [s.title for s in state["report"].sections]
        self.assertEqual(titles, ["First", "Second", "Third"])


class TestAddCitation(SimpleTestCase):
    def test_appends_citation(self):
        state = _state_with_empty_report()
        result = _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id=_VALID_TRACE_ID,
            reason="high_cost",
        )
        self.assertEqual(len(state["report"].citations), 1)
        cit = state["report"].citations[0]
        self.assertIsInstance(cit, Citation)
        self.assertEqual(cit.generation_id, _VALID_GEN_ID)
        self.assertEqual(cit.trace_id, _VALID_TRACE_ID)
        self.assertEqual(cit.reason, "high_cost")
        self.assertIn("Citation", result)

    def test_rejects_non_uuid_generation_id(self):
        state = _state_with_empty_report()
        result = _add_citation_fn(
            state=state,
            generation_id="not-a-uuid",
            trace_id=_VALID_TRACE_ID,
            reason="r",
        )
        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_accepts_opaque_trace_id(self):
        state = _state_with_empty_report()
        result = _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id="also-not-a-uuid",
            reason="r",
        )
        self.assertNotIn("Error", result)
        self.assertEqual(state["report"].citations[0].trace_id, "also-not-a-uuid")

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_trace_target_allows_evaluated_trace_with_empty_generation_id(self, mock_execute_hogql: MagicMock) -> None:
        state = _trace_report_tool_state()
        mock_execute_hogql.return_value = [["customer/trace:42"]]
        result = _add_citation_fn(
            state=state,
            generation_id="",
            trace_id="customer/trace:42",
            reason="failed criteria",
        )

        self.assertNotIn("Error", result)
        self.assertEqual(
            state["report"].citations[0],
            Citation(generation_id="", trace_id="customer/trace:42", reason="failed criteria"),
        )

    @patch("posthog.temporal.ai_observability.eval_reports.report_agent.tools._execute_hogql")
    def test_trace_target_rejects_citation_outside_evaluation_period(self, mock_execute_hogql: MagicMock) -> None:
        state = _trace_report_tool_state()
        mock_execute_hogql.return_value = []

        result = _add_citation_fn(
            state=state,
            generation_id="",
            trace_id="unrelated-trace",
            reason="failed criteria",
        )

        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_trace_target_rejects_generation_id(self):
        state = _state_with_empty_report(evaluation_target="trace")

        result = _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id="customer/trace:42",
            reason="failed criteria",
        )

        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_rejects_trace_id_with_control_characters(self):
        state = _state_with_empty_report(evaluation_target="trace")
        result = _add_citation_fn(state=state, generation_id="", trace_id="trace\nother", reason="r")

        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_rejects_empty_ids(self):
        state = _state_with_empty_report()
        result = _add_citation_fn(state=state, generation_id="", trace_id="", reason="r")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_clips_very_long_reason(self):
        state = _state_with_empty_report()
        long_reason = "x" * 500
        _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id=_VALID_TRACE_ID,
            reason=long_reason,
        )
        self.assertLessEqual(len(state["report"].citations[0].reason), 200)

    def test_multiple_citations_preserve_order(self):
        state = _state_with_empty_report()
        _add_citation_fn(state=state, generation_id=_VALID_GEN_ID, trace_id=_VALID_TRACE_ID, reason="first")
        _add_citation_fn(state=state, generation_id=_VALID_GEN_ID, trace_id=_VALID_TRACE_ID, reason="second")
        self.assertEqual(len(state["report"].citations), 2)
        self.assertEqual(state["report"].citations[0].reason, "first")
        self.assertEqual(state["report"].citations[1].reason, "second")


class TestListAndGetReportRun(BaseTest):
    """DB-backed tests for the split list_recent_report_runs + get_report_run tools."""

    def setUp(self):
        super().setUp()
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
        from products.ai_observability.backend.models.evaluations import Evaluation

        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        self.report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=self.evaluation,
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold=100,
            delivery_targets=[],
            created_by=self.user,
        )
        self.EvaluationReportRun = EvaluationReportRun

        now = timezone.now()
        # Three prior runs, ending in ascending order so we can assert the most
        # recent comes first.
        self.older_run = EvaluationReportRun.objects.create(
            report=self.report,
            content={"title": "Older report", "sections": []},
            metadata={"pass_rate": 85.0, "total_runs": 20},
            period_start=now - dt.timedelta(days=14),
            period_end=now - dt.timedelta(days=13),
        )
        self.recent_run = EvaluationReportRun.objects.create(
            report=self.report,
            content={"title": "Recent report", "sections": [{"title": "Summary", "content": "foo"}]},
            metadata={"pass_rate": 94.2, "total_runs": 53},
            period_start=now - dt.timedelta(days=2),
            period_end=now - dt.timedelta(days=1),
        )
        self.state = {
            "evaluation_id": str(self.evaluation.id),
            "period_start": now.isoformat(),
        }

    def test_list_returns_compact_index_newest_first(self):
        result = json.loads(_list_recent_report_runs_fn(state=self.state))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["title"], "Recent report")
        self.assertEqual(result[0]["pass_rate"], 94.2)
        self.assertEqual(result[0]["total_runs"], 53)
        self.assertNotIn("result_rates", result[0])
        self.assertIn("run_id", result[0])
        # Full content intentionally omitted
        self.assertNotIn("content", result[0])

    def test_list_filters_by_since_days(self):
        result = json.loads(_list_recent_report_runs_fn(state=self.state, since_days=3))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Recent report")

    def test_list_clamps_limit(self):
        # limit > 200 should be clamped; easier to assert by passing 0 and checking clamp to 1
        result = json.loads(_list_recent_report_runs_fn(state=self.state, limit=0))
        self.assertEqual(len(result), 1)

    def test_get_returns_full_content(self):
        result = json.loads(_get_report_run_fn(state=self.state, run_id=str(self.recent_run.id)))
        self.assertEqual(result["content"]["title"], "Recent report")
        self.assertEqual(len(result["content"]["sections"]), 1)
        self.assertEqual(result["metadata"]["pass_rate"], 94.2)
        self.assertNotIn("result_counts", result["metadata"])
        self.assertNotIn("result_rates", result["metadata"])

    def test_history_is_scoped_to_the_current_evaluation_target(self):
        now = timezone.now()
        trace_run = self.EvaluationReportRun.objects.create(
            report=self.report,
            content={"evaluation_target": "trace", "title": "Trace report", "sections": []},
            metadata={"pass_rate": 50.0, "total_runs": 2},
            period_start=now - dt.timedelta(hours=2),
            period_end=now - dt.timedelta(hours=1),
        )

        generation_runs = json.loads(_list_recent_report_runs_fn(state=self.state))
        trace_state = {**self.state, "evaluation_target": "trace"}
        trace_runs = json.loads(_list_recent_report_runs_fn(state=trace_state))

        self.assertNotIn(str(trace_run.id), {run["run_id"] for run in generation_runs})
        self.assertEqual([run["run_id"] for run in trace_runs], [str(trace_run.id)])
        self.assertIn("error", json.loads(_get_report_run_fn(state=self.state, run_id=str(trace_run.id))))
        self.assertEqual(
            json.loads(_get_report_run_fn(state=trace_state, run_id=str(trace_run.id)))["content"]["title"],
            "Trace report",
        )

    def test_list_includes_back_to_back_previous_run(self):
        # Regression: period_end exactly equal to the current period_start used to be
        # excluded by a strict `lt` filter, dropping the immediately previous report —
        # the most useful one for delta/continuity analysis.
        boundary_start = dt.datetime.fromisoformat(self.state["period_start"])
        boundary_run = self.EvaluationReportRun.objects.create(
            report=self.report,
            content={"title": "Back-to-back report", "sections": []},
            metadata={"pass_rate": 77.7, "total_runs": 11},
            period_start=boundary_start - dt.timedelta(hours=1),
            period_end=boundary_start,
        )
        result = json.loads(_list_recent_report_runs_fn(state=self.state))
        titles = [r["title"] for r in result]
        self.assertIn("Back-to-back report", titles)
        boundary_entry = next(r for r in result if r["run_id"] == str(boundary_run.id))
        self.assertEqual(boundary_entry["pass_rate"], 77.7)
        self.assertEqual(boundary_entry["total_runs"], 11)

    def test_list_falls_back_to_content_metrics_when_metadata_empty(self):
        # The agent's output contract carries metrics inside content; only the
        # downstream store activity mirrors them into metadata. The tool must read
        # either source so it stays correct if the mirror is removed.
        now = timezone.now()
        content_only_run = self.EvaluationReportRun.objects.create(
            report=self.report,
            content={
                "title": "Content-only metrics",
                "sections": [],
                "metrics": {
                    "total_runs": 8,
                    "result_counts": {"pass": 6, "fail": 2, "na": 0},
                },
            },
            metadata={},
            period_start=now - dt.timedelta(hours=2),
            period_end=now - dt.timedelta(hours=1),
        )
        result = json.loads(_list_recent_report_runs_fn(state=self.state))
        entry = next(r for r in result if r["run_id"] == str(content_only_run.id))
        self.assertEqual(entry["pass_rate"], 75.0)
        self.assertEqual(entry["result_rates"], {"pass": 75.0, "fail": 25.0, "na": 0.0})
        self.assertEqual(entry["total_runs"], 8)

    def test_get_rejects_non_uuid(self):
        result = json.loads(_get_report_run_fn(state=self.state, run_id="not-a-uuid"))
        self.assertIn("error", result)

    def test_get_rejects_run_from_other_evaluation(self):
        # Another evaluation with its own report + run
        from products.ai_observability.backend.models.evaluations import Evaluation

        other_eval = Evaluation.objects.create(
            team=self.team,
            name="Other Eval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "other"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        from products.ai_observability.backend.models.evaluation_reports import EvaluationReport

        other_report = EvaluationReport.objects.create(
            team=self.team,
            evaluation=other_eval,
            frequency=EvaluationReport.Frequency.EVERY_N,
            trigger_threshold=100,
            delivery_targets=[],
            created_by=self.user,
        )
        other_run = self.EvaluationReportRun.objects.create(
            report=other_report,
            content={"title": "Other"},
            metadata={},
            period_start=timezone.now() - dt.timedelta(days=1),
            period_end=timezone.now(),
        )
        # Agent state is scoped to self.evaluation — other_run must not be visible
        result = json.loads(_get_report_run_fn(state=self.state, run_id=str(other_run.id)))
        self.assertIn("error", result)


class TestToolsCoordinate(SimpleTestCase):
    """Smoke: a realistic agent-like sequence of calls produces a valid report."""

    def test_full_agent_sequence(self):
        state = _state_with_empty_report()
        _set_title_fn(state=state, title="Pass rate steady, one bucket dip")
        _add_section_fn(state=state, title="Summary", content="Overall healthy.")
        _add_section_fn(
            state=state,
            title="14:00 bucket",
            content="Dropped to 50% pass rate in the 14:00 bucket.",
        )
        _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id=_VALID_TRACE_ID,
            reason="14:00_bucket_fail",
        )

        report = state["report"]
        self.assertEqual(report.title, "Pass rate steady, one bucket dip")
        self.assertEqual(len(report.sections), 2)
        self.assertIsInstance(report.sections[0], ReportSection)
        self.assertEqual(len(report.citations), 1)
