"""Tests for the v2 eval report agent output tools (set_title, add_section, add_citation)."""

import json
import datetime as dt

from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    MAX_REPORT_SECTIONS,
    Citation,
    EvalReportContent,
    ReportSection,
)
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import (
    _UUID_RE,
    _ch_ts,
    _widened_ts_window,
    add_citation,
    add_section,
    get_report_run,
    list_recent_report_runs,
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


def _state_with_empty_report() -> dict:
    """Build a minimal state dict with an empty EvalReportContent (matches runtime)."""
    return {"report": EvalReportContent()}


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

    def test_rejects_non_uuid_trace_id(self):
        state = _state_with_empty_report()
        result = _add_citation_fn(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id="also-not-a-uuid",
            reason="r",
        )
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
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport, EvaluationReportRun
        from products.llm_analytics.backend.models.evaluations import Evaluation

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
                "metrics": {"pass_rate": 42.5, "total_runs": 8},
            },
            metadata={},
            period_start=now - dt.timedelta(hours=2),
            period_end=now - dt.timedelta(hours=1),
        )
        result = json.loads(_list_recent_report_runs_fn(state=self.state))
        entry = next(r for r in result if r["run_id"] == str(content_only_run.id))
        self.assertEqual(entry["pass_rate"], 42.5)
        self.assertEqual(entry["total_runs"], 8)

    def test_get_rejects_non_uuid(self):
        result = json.loads(_get_report_run_fn(state=self.state, run_id="not-a-uuid"))
        self.assertIn("error", result)

    def test_get_rejects_run_from_other_evaluation(self):
        # Another evaluation with its own report + run
        from products.llm_analytics.backend.models.evaluations import Evaluation

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
        from products.llm_analytics.backend.models.evaluation_reports import EvaluationReport

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
