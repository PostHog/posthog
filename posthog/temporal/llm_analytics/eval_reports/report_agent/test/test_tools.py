from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import REPORT_SECTIONS, ReportSection
from posthog.temporal.llm_analytics.eval_reports.report_agent.tools import (
    UUID_PATTERN,
    _ch_ts,
    finalize_report,
    set_report_section,
)


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


class TestUuidPattern(SimpleTestCase):
    def test_extracts_uuids_from_backticks(self):
        text = "See generation `12345678-1234-1234-1234-123456789abc` and `abcdefab-cdef-abcd-efab-cdefabcdefab`."
        matches = UUID_PATTERN.findall(text)
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0], "12345678-1234-1234-1234-123456789abc")

    def test_no_match_without_backticks(self):
        text = "See 12345678-1234-1234-1234-123456789abc."
        matches = UUID_PATTERN.findall(text)
        self.assertEqual(len(matches), 0)


class TestSetReportSection(SimpleTestCase):
    def test_sets_section_with_content(self):
        state = {"report": {}}
        result = set_report_section.func(
            state=state,
            section="executive_summary",
            content="Pass rate is 85%.",
        )
        self.assertIn("executive_summary", state["report"])
        self.assertEqual(state["report"]["executive_summary"].content, "Pass rate is 85%.")
        self.assertIn("executive_summary", result)

    def test_extracts_generation_ids(self):
        state = {"report": {}}
        set_report_section.func(
            state=state,
            section="failure_patterns",
            content="Failed: `12345678-1234-1234-1234-123456789abc` and `abcdefab-cdef-abcd-efab-cdefabcdefab`.",
        )
        section = state["report"]["failure_patterns"]
        self.assertEqual(len(section.referenced_generation_ids), 2)

    def test_invalid_section_returns_error(self):
        state = {"report": {}}
        result = set_report_section.func(state=state, section="nonexistent", content="test")
        self.assertIn("Invalid section", result)
        self.assertNotIn("nonexistent", state["report"])

    @parameterized.expand([(name,) for name in REPORT_SECTIONS])
    def test_accepts_all_valid_sections(self, section_name):
        state = {"report": {}}
        result = set_report_section.func(state=state, section=section_name, content="content")
        self.assertIn(section_name, state["report"])
        self.assertNotIn("Invalid", result)


class TestFinalizeReport(SimpleTestCase):
    def test_finalize_with_all_sections(self):
        report = {name: ReportSection(content="x") for name in REPORT_SECTIONS}
        state = {"report": report}
        result = finalize_report.func(state=state)
        self.assertIn(str(len(REPORT_SECTIONS)), result)

    def test_finalize_with_partial_sections(self):
        state = {"report": {"executive_summary": ReportSection(content="x")}}
        result = finalize_report.func(state=state)
        self.assertIn("1 sections", result)
        self.assertIn("executive_summary", result)

    def test_finalize_with_no_sections(self):
        state = {"report": {}}
        result = finalize_report.func(state=state)
        self.assertIn("0 sections", result)
