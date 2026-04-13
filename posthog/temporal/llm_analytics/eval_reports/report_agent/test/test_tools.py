"""Tests for the v2 eval report agent output tools (set_title, add_section, add_citation)."""

from django.test import SimpleTestCase

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
    add_citation,
    add_section,
    set_title,
)

_VALID_GEN_ID = "12345678-1234-1234-1234-123456789abc"
_VALID_TRACE_ID = "abcdefab-cdef-abcd-efab-cdefabcdefab"


def _state_with_empty_report() -> dict:
    """Build a minimal state dict with an empty EvalReportContent (matches runtime)."""
    return {"report": EvalReportContent()}


class TestChTs(SimpleTestCase):
    @parameterized.expand(
        [
            ("iso_with_tz", "2026-03-12T10:05:48.034000+00:00", "2026-03-12 10:05:48.034000"),
            ("iso_no_tz", "2026-03-12T10:05:48.034000", "2026-03-12 10:05:48.034000"),
            ("iso_z_suffix", "2026-03-12T10:05:48.034000Z", "2026-03-12 10:05:48.034000"),
            ("no_microseconds", "2026-03-12T10:05:48+00:00", "2026-03-12 10:05:48.000000"),
            ("different_timezone", "2026-03-12T12:05:48+02:00", "2026-03-12 10:05:48.000000"),
        ]
    )
    def test_converts_iso_to_clickhouse_format(self, _name, iso_input, expected):
        self.assertEqual(_ch_ts(iso_input), expected)


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
        result = set_title.func(state=state, title="Pass rate steady at 94%")
        self.assertEqual(state["report"].title, "Pass rate steady at 94%")
        self.assertIn("Pass rate steady at 94%", result)

    def test_strips_whitespace(self):
        state = _state_with_empty_report()
        set_title.func(state=state, title="  padded title  ")
        self.assertEqual(state["report"].title, "padded title")

    def test_rejects_empty_title(self):
        state = _state_with_empty_report()
        result = set_title.func(state=state, title="")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].title, "")

    def test_rejects_whitespace_only_title(self):
        state = _state_with_empty_report()
        result = set_title.func(state=state, title="   ")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].title, "")

    def test_clips_very_long_title(self):
        state = _state_with_empty_report()
        long_title = "x" * 500
        set_title.func(state=state, title=long_title)
        self.assertLessEqual(len(state["report"].title), 200)
        self.assertTrue(state["report"].title.endswith("..."))


class TestAddSection(SimpleTestCase):
    def test_appends_section(self):
        state = _state_with_empty_report()
        result = add_section.func(state=state, title="Summary", content="Pass rate is 94%.")
        self.assertEqual(len(state["report"].sections), 1)
        self.assertEqual(state["report"].sections[0].title, "Summary")
        self.assertEqual(state["report"].sections[0].content, "Pass rate is 94%.")
        self.assertIn("Summary", result)

    def test_rejects_empty_title(self):
        state = _state_with_empty_report()
        result = add_section.func(state=state, title="", content="body")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].sections, [])

    def test_rejects_empty_content(self):
        state = _state_with_empty_report()
        result = add_section.func(state=state, title="Summary", content="")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].sections, [])

    def test_allows_up_to_max_sections(self):
        state = _state_with_empty_report()
        for i in range(MAX_REPORT_SECTIONS):
            result = add_section.func(state=state, title=f"Section {i}", content=f"Body {i}")
            self.assertNotIn("Error", result)
        self.assertEqual(len(state["report"].sections), MAX_REPORT_SECTIONS)

    def test_rejects_over_max_sections(self):
        state = _state_with_empty_report()
        # Fill to the max
        for i in range(MAX_REPORT_SECTIONS):
            add_section.func(state=state, title=f"Section {i}", content="body")
        # Next one should be rejected
        result = add_section.func(state=state, title="One too many", content="body")
        self.assertIn("Error", result)
        self.assertIn("maximum", result)
        self.assertEqual(len(state["report"].sections), MAX_REPORT_SECTIONS)

    def test_preserves_section_order(self):
        state = _state_with_empty_report()
        add_section.func(state=state, title="First", content="a")
        add_section.func(state=state, title="Second", content="b")
        add_section.func(state=state, title="Third", content="c")
        titles = [s.title for s in state["report"].sections]
        self.assertEqual(titles, ["First", "Second", "Third"])


class TestAddCitation(SimpleTestCase):
    def test_appends_citation(self):
        state = _state_with_empty_report()
        result = add_citation.func(
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
        result = add_citation.func(
            state=state,
            generation_id="not-a-uuid",
            trace_id=_VALID_TRACE_ID,
            reason="r",
        )
        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_rejects_non_uuid_trace_id(self):
        state = _state_with_empty_report()
        result = add_citation.func(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id="also-not-a-uuid",
            reason="r",
        )
        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_rejects_empty_ids(self):
        state = _state_with_empty_report()
        result = add_citation.func(state=state, generation_id="", trace_id="", reason="r")
        self.assertIn("Error", result)
        self.assertEqual(state["report"].citations, [])

    def test_clips_very_long_reason(self):
        state = _state_with_empty_report()
        long_reason = "x" * 500
        add_citation.func(
            state=state,
            generation_id=_VALID_GEN_ID,
            trace_id=_VALID_TRACE_ID,
            reason=long_reason,
        )
        self.assertLessEqual(len(state["report"].citations[0].reason), 200)

    def test_multiple_citations_preserve_order(self):
        state = _state_with_empty_report()
        add_citation.func(state=state, generation_id=_VALID_GEN_ID, trace_id=_VALID_TRACE_ID, reason="first")
        add_citation.func(state=state, generation_id=_VALID_GEN_ID, trace_id=_VALID_TRACE_ID, reason="second")
        self.assertEqual(len(state["report"].citations), 2)
        self.assertEqual(state["report"].citations[0].reason, "first")
        self.assertEqual(state["report"].citations[1].reason, "second")


class TestToolsCoordinate(SimpleTestCase):
    """Smoke: a realistic agent-like sequence of calls produces a valid report."""

    def test_full_agent_sequence(self):
        state = _state_with_empty_report()
        set_title.func(state=state, title="Pass rate steady, one bucket dip")
        add_section.func(state=state, title="Summary", content="Overall healthy.")
        add_section.func(
            state=state,
            title="14:00 bucket",
            content="Dropped to 50% pass rate in the 14:00 bucket.",
        )
        add_citation.func(
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
