from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.temporal.llm_analytics.eval_reports.delivery import (
    UUID_LINK_PATTERN,
    _inline_email_styles,
    _linkify_uuids,
    _render_section_html,
    _render_section_mrkdwn,
    deliver_report,
)
from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import EvalReportContent, ReportSection


class TestUuidLinkPattern(SimpleTestCase):
    def test_matches_backtick_uuids(self):
        text = "See `12345678-1234-1234-1234-123456789abc` for details."
        matches = UUID_LINK_PATTERN.findall(text)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0], "12345678-1234-1234-1234-123456789abc")

    def test_no_match_without_backticks(self):
        text = "ID 12345678-1234-1234-1234-123456789abc is referenced."
        matches = UUID_LINK_PATTERN.findall(text)
        self.assertEqual(len(matches), 0)


class TestLinkifyUuids(SimpleTestCase):
    def test_converts_uuid_to_markdown_link(self):
        text = "See `12345678-1234-1234-1234-123456789abc` here."
        result = _linkify_uuids(text, project_id=42)
        self.assertIn("[12345678...]", result)
        self.assertIn("/project/42/llm-analytics/traces/12345678-1234-1234-1234-123456789abc", result)

    def test_leaves_non_uuid_backticks_alone(self):
        text = "Use `some_function()` here."
        result = _linkify_uuids(text, project_id=1)
        self.assertEqual(text, result)


class TestRenderSectionHtml(SimpleTestCase):
    def test_renders_title(self):
        html = _render_section_html("executive_summary", "Some content", project_id=1)
        self.assertIn("<h2>Executive Summary</h2>", html)

    def test_renders_bold_markdown(self):
        html = _render_section_html("statistics", "**Pass rate**: 80%", project_id=1)
        self.assertIn("<strong>Pass rate</strong>", html)

    def test_converts_uuid_to_link(self):
        html = _render_section_html(
            "failure_patterns",
            "Failed: `12345678-1234-1234-1234-123456789abc`",
            project_id=42,
        )
        self.assertIn("/project/42/llm-analytics/traces/12345678-1234-1234-1234-123456789abc", html)
        self.assertIn("12345678...", html)

    def test_unknown_section_uses_title_case(self):
        html = _render_section_html("some_custom", "content", project_id=1)
        self.assertIn("<h2>Some Custom</h2>", html)

    def test_renders_lists(self):
        html = _render_section_html("statistics", "- item 1\n- item 2", project_id=1)
        self.assertIn("<li>item 1</li>", html)
        self.assertIn("<li>item 2</li>", html)
        self.assertIn("<ul>", html)

    def test_renders_tables(self):
        md = "| Metric | Value |\n|--------|-------|\n| Pass rate | 80% |"
        html = _render_section_html("statistics", md, project_id=1)
        self.assertIn("<table", html)
        self.assertIn("<th", html)
        self.assertIn("Pass rate", html)

    def test_renders_italic(self):
        html = _render_section_html("statistics", "*emphasis*", project_id=1)
        self.assertIn("<em>emphasis</em>", html)


class TestInlineEmailStyles(SimpleTestCase):
    def test_adds_table_styles(self):
        html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        styled = _inline_email_styles(html)
        self.assertIn("border-collapse", styled)
        self.assertIn("background-color", styled)

    def test_no_op_without_tables(self):
        html = "<p>Just text</p>"
        self.assertEqual(html, _inline_email_styles(html))


class TestRenderSectionMrkdwn(SimpleTestCase):
    def test_renders_title_bold(self):
        result = _render_section_mrkdwn("executive_summary", "Some content")
        self.assertIn("*Executive Summary*", result)

    def test_converts_bold(self):
        result = _render_section_mrkdwn("statistics", "**Pass rate**: 80%")
        self.assertIn("*Pass rate*", result)

    def test_converts_lists(self):
        result = _render_section_mrkdwn("statistics", "- item 1\n- item 2")
        # SlackMarkdownConverter uses bullet chars
        self.assertIn("item 1", result)
        self.assertIn("item 2", result)


class TestDeliverReport(SimpleTestCase):
    def _make_report_run(self):
        run = MagicMock()
        run.content = EvalReportContent(
            executive_summary=ReportSection(content="summary"),
        ).to_dict()
        run.period_start = MagicMock(isoformat=MagicMock(return_value="2026-03-01T00:00:00+00:00"))
        run.period_end = MagicMock(isoformat=MagicMock(return_value="2026-03-02T00:00:00+00:00"))
        run.report_id = "report-id"
        run.id = "run-id"
        return run

    def _make_report(self, targets):
        report = MagicMock()
        report.evaluation.name = "Test Eval"
        report.team.id = 1
        report.team_id = 1
        report.delivery_targets = targets
        return report

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_deliver_report_calls_email(self, mock_report_qs, mock_run_qs, mock_slack, mock_email):
        targets = [{"type": "email", "value": "test@example.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = []

        deliver_report("report-id", "run-id")

        mock_email.assert_called_once()
        mock_slack.assert_not_called()
        self.assertEqual(run.delivery_status, "delivered")

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_deliver_report_handles_failures(self, mock_report_qs, mock_run_qs, mock_slack, mock_email):
        targets = [{"type": "email", "value": "test@example.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = ["send failed"]

        # Full failure must raise so the Temporal activity surfaces it and the
        # retry policy can take effect — but only after persisting state.
        with self.assertRaises(RuntimeError) as cm:
            deliver_report("report-id", "run-id")
        self.assertIn("send failed", str(cm.exception))

        self.assertEqual(run.delivery_status, "failed")
        self.assertEqual(run.delivery_errors, ["send failed"])

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_deliver_report_partial_failure(self, mock_report_qs, mock_run_qs, mock_slack, mock_email):
        targets = [
            {"type": "email", "value": "test@example.com"},
            {"type": "slack", "integration_id": 1, "channel": "#reports"},
        ]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = []
        mock_slack.return_value = ["slack failed"]

        deliver_report("report-id", "run-id")

        self.assertEqual(run.delivery_status, "partial_failure")
