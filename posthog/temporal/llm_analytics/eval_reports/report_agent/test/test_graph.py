from django.test import SimpleTestCase

from posthog.temporal.llm_analytics.eval_reports.report_agent.graph import _fill_missing_sections
from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportMetadata, ReportSection


class TestFillMissingSections(SimpleTestCase):
    def test_preserves_existing_sections(self):
        report = {"executive_summary": ReportSection(content="custom summary")}
        metadata = EvalReportMetadata(total_runs=100, pass_count=80, fail_count=20, pass_rate=80.0)
        content = _fill_missing_sections(report, metadata)
        self.assertEqual(content.executive_summary.content, "custom summary")

    def test_fills_executive_summary_when_missing(self):
        metadata = EvalReportMetadata(total_runs=50, pass_count=40, fail_count=10, pass_rate=80.0)
        content = _fill_missing_sections({}, metadata)
        self.assertIsNotNone(content.executive_summary)
        self.assertIn("80.0%", content.executive_summary.content)
        self.assertIn("50", content.executive_summary.content)

    def test_fills_statistics_when_missing(self):
        metadata = EvalReportMetadata(total_runs=100, pass_count=75, fail_count=20, na_count=5, pass_rate=78.95)
        content = _fill_missing_sections({}, metadata)
        self.assertIsNotNone(content.statistics)
        self.assertIn("100", content.statistics.content)
        self.assertIn("75", content.statistics.content)

    def test_trend_up(self):
        metadata = EvalReportMetadata(pass_rate=85.0, previous_pass_rate=70.0, total_runs=10)
        content = _fill_missing_sections({}, metadata)
        self.assertIn("up from", content.executive_summary.content)

    def test_trend_down(self):
        metadata = EvalReportMetadata(pass_rate=60.0, previous_pass_rate=80.0, total_runs=10)
        content = _fill_missing_sections({}, metadata)
        self.assertIn("down from", content.executive_summary.content)

    def test_trend_stable(self):
        metadata = EvalReportMetadata(pass_rate=80.0, previous_pass_rate=80.5, total_runs=10)
        content = _fill_missing_sections({}, metadata)
        self.assertIn("stable", content.executive_summary.content)

    def test_no_metadata_returns_empty_content(self):
        content = _fill_missing_sections({}, None)
        self.assertIsNone(content.executive_summary)
        self.assertIsNone(content.statistics)

    def test_empty_report_with_none_metadata(self):
        content = _fill_missing_sections({}, None)
        self.assertEqual(content.to_dict(), {})
