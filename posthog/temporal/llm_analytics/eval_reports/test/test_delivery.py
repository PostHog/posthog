from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.temporal.llm_analytics.eval_reports.delivery import (
    _format_period_for_display,
    _inline_email_styles,
    _linkify_citations,
    _render_metrics_block_html,
    _render_section_html,
    _render_section_mrkdwn,
    _strip_redundant_leading_heading,
    deliver_report,
)
from posthog.temporal.llm_analytics.eval_reports.report_agent.schema import (
    Citation,
    EvalReportContent,
    EvalReportMetrics,
    ReportSection,
)


class TestLinkifyCitations(SimpleTestCase):
    def test_links_cited_generation_id_in_backticks(self):
        text = "See `12345678-1234-1234-1234-123456789abc` here."
        citation_map = {"12345678-1234-1234-1234-123456789abc": "trace-abc"}
        result = _linkify_citations(text, project_id=42, citation_map=citation_map)
        self.assertIn("[12345678...]", result)
        self.assertIn("/project/42/llm-analytics/traces/trace-abc?event=12345678-1234-1234-1234-123456789abc", result)

    def test_links_cited_generation_id_in_double_backticks(self):
        text = "See `` `12345678-1234-1234-1234-123456789abc` `` here."
        citation_map = {"12345678-1234-1234-1234-123456789abc": "trace-abc"}
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertIn("[12345678...]", result)
        self.assertNotIn("``", result)

    def test_links_cited_generation_id_bare(self):
        text = "See 12345678-1234-1234-1234-123456789abc here."
        citation_map = {"12345678-1234-1234-1234-123456789abc": "trace-abc"}
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertIn("[12345678...]", result)

    def test_leaves_uncited_ids_alone(self):
        text = "See `12345678-1234-1234-1234-123456789abc` here."
        result = _linkify_citations(text, project_id=1, citation_map={})
        self.assertEqual(text, result)

    def test_leaves_non_id_backticks_alone(self):
        text = "Use `some_function()` here."
        citation_map = {"12345678-1234-1234-1234-123456789abc": "trace-abc"}
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertEqual(text, result)

    def test_no_double_replacement_when_id_appears_multiple_times(self):
        gen_id = "639a38ba-6cc6-4e0c-b5ff-ad269f6f9cf6"
        citation_map = {gen_id: "trace-abc"}
        text = f"- `{gen_id}`: satisfied\n1. {gen_id} — reason"
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertNotIn(f"?event=[", result)
        self.assertNotIn(f"?event=%5B", result)
        self.assertEqual(result.count("[639a38ba...]"), 2)

    def test_multiple_citations_no_cross_contamination(self):
        citation_map = {
            "aaaa1111-1111-1111-1111-111111111111": "trace-a",
            "bbbb2222-2222-2222-2222-222222222222": "trace-b",
        }
        text = "First: `aaaa1111-1111-1111-1111-111111111111`, second: `bbbb2222-2222-2222-2222-222222222222`."
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertIn("traces/trace-a?event=aaaa1111", result)
        self.assertIn("traces/trace-b?event=bbbb2222", result)
        self.assertNotIn("?event=[", result)

    def test_handles_non_uuid_trace_id(self):
        text = "See `gen-123` here."
        citation_map = {"gen-123": "my-custom-trace-id"}
        result = _linkify_citations(text, project_id=1, citation_map=citation_map)
        self.assertIn("/traces/my-custom-trace-id?event=gen-123", result)


class TestRenderSectionHtml(SimpleTestCase):
    """v2: renderer takes a title directly, no more SECTION_TITLES lookup."""

    def test_renders_title_as_h2(self):
        html = _render_section_html("Summary", "Some content", project_id=1, citation_map={})
        self.assertIn("<h2>Summary</h2>", html)

    def test_renders_agent_chosen_title(self):
        html = _render_section_html("Volume drop at 14:00", "body", project_id=1, citation_map={})
        self.assertIn("<h2>Volume drop at 14:00</h2>", html)

    def test_renders_bold_markdown(self):
        html = _render_section_html("Stats", "**Pass rate**: 80%", project_id=1, citation_map={})
        self.assertIn("<strong>Pass rate</strong>", html)

    def test_converts_cited_id_to_link(self):
        citation_map = {"12345678-1234-1234-1234-123456789abc": "trace-abc"}
        html = _render_section_html(
            "Failures",
            "Failed: `12345678-1234-1234-1234-123456789abc`",
            project_id=42,
            citation_map=citation_map,
        )
        self.assertIn("/project/42/llm-analytics/traces/trace-abc", html)
        self.assertIn("12345678...", html)

    def test_renders_lists(self):
        html = _render_section_html("Stats", "- item 1\n- item 2", project_id=1, citation_map={})
        self.assertIn("<li>item 1</li>", html)
        self.assertIn("<li>item 2</li>", html)
        self.assertIn("<ul>", html)

    def test_renders_tables(self):
        md = "| Metric | Value |\n|--------|-------|\n| Pass rate | 80% |"
        html = _render_section_html("Stats", md, project_id=1, citation_map={})
        self.assertIn("<table", html)
        self.assertIn("<th", html)
        self.assertIn("Pass rate", html)

    def test_renders_italic(self):
        html = _render_section_html("Stats", "*emphasis*", project_id=1, citation_map={})
        self.assertIn("<em>emphasis</em>", html)


class TestRenderSectionMrkdwn(SimpleTestCase):
    def test_renders_title_bold(self):
        result = _render_section_mrkdwn("Summary", "Some content", project_id=1, citation_map={})
        self.assertIn("*Summary*", result)

    def test_renders_agent_chosen_title(self):
        result = _render_section_mrkdwn("Cost spike in gpt-5.2", "Body", project_id=1, citation_map={})
        self.assertIn("*Cost spike in gpt-5.2*", result)

    def test_converts_bold(self):
        result = _render_section_mrkdwn("Stats", "**Pass rate**: 80%", project_id=1, citation_map={})
        self.assertIn("*Pass rate*", result)

    def test_converts_lists(self):
        result = _render_section_mrkdwn("Stats", "- item 1\n- item 2", project_id=1, citation_map={})
        self.assertIn("item 1", result)
        self.assertIn("item 2", result)


class TestStripRedundantLeadingHeading(SimpleTestCase):
    def test_strips_exact_match(self):
        content = "## Executive Summary\n\nPass rate is 94%."
        result = _strip_redundant_leading_heading(content, "Executive Summary")
        self.assertEqual(result, "Pass rate is 94%.")

    def test_strips_case_insensitive(self):
        content = "## executive summary\n\nBody text."
        result = _strip_redundant_leading_heading(content, "Executive Summary")
        self.assertEqual(result, "Body text.")

    def test_strips_with_suffix(self):
        # The agent sometimes emits "Trend analysis (hourly)" as the heading
        content = "## Trend analysis (hourly)\n\n- 13:00 bucket: 96%"
        result = _strip_redundant_leading_heading(content, "Trend Analysis")
        self.assertEqual(result, "- 13:00 bucket: 96%")

    def test_strips_h1_through_h6(self):
        for prefix in ("#", "##", "###", "####", "#####", "######"):
            content = f"{prefix} Statistics\n\nBody"
            result = _strip_redundant_leading_heading(content, "Statistics")
            self.assertEqual(result, "Body", f"failed for prefix {prefix!r}")

    def test_leaves_content_alone_when_no_heading(self):
        content = "Pass rate is 94%."
        result = _strip_redundant_leading_heading(content, "Executive Summary")
        self.assertEqual(result, content)

    def test_leaves_content_alone_when_heading_does_not_match(self):
        content = "## Something Else\n\nBody"
        result = _strip_redundant_leading_heading(content, "Executive Summary")
        self.assertEqual(result, content)

    def test_does_not_strip_non_leading_headings(self):
        content = "Intro paragraph.\n\n## Executive Summary\n\nBody"
        result = _strip_redundant_leading_heading(content, "Executive Summary")
        self.assertEqual(result, content)

    def test_render_section_html_does_not_duplicate_heading(self):
        content = "## Summary\n\nPass rate is 94%."
        html = _render_section_html("Summary", content, project_id=1, citation_map={})
        self.assertEqual(html.count("Summary"), 1)
        self.assertIn("<h2>Summary</h2>", html)
        self.assertIn("Pass rate is 94%", html)

    def test_render_section_mrkdwn_does_not_duplicate_heading(self):
        content = "## Summary\n\nPass rate is 94%."
        result = _render_section_mrkdwn("Summary", content, project_id=1, citation_map={})
        self.assertEqual(result.count("Summary"), 1)
        self.assertTrue(result.startswith("*Summary*"))


class TestFormatPeriodForDisplay(SimpleTestCase):
    def test_formats_utc_iso_timestamp(self):
        result = _format_period_for_display("2026-04-08T14:01:42.951661+00:00")
        self.assertEqual(result, "Apr 08, 2026 14:01 UTC")

    def test_formats_non_utc_iso_timestamp_by_converting_to_utc(self):
        # 10:00 in America/New_York (UTC-4 in April) → 14:00 UTC
        result = _format_period_for_display("2026-04-08T10:00:00-04:00")
        self.assertEqual(result, "Apr 08, 2026 14:00 UTC")

    def test_falls_back_to_raw_string_on_parse_error(self):
        result = _format_period_for_display("not a timestamp")
        self.assertEqual(result, "not a timestamp")

    def test_falls_back_on_none(self):
        result = _format_period_for_display(None)  # type: ignore[arg-type]
        self.assertIsNone(result)


class TestInlineEmailStyles(SimpleTestCase):
    def test_adds_table_styles(self):
        html = "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        styled = _inline_email_styles(html)
        self.assertIn("border-collapse", styled)
        self.assertIn("background-color", styled)

    def test_no_op_without_tables(self):
        html = "<p>Just text</p>"
        self.assertEqual(html, _inline_email_styles(html))


class TestMetricsBlockHtml(SimpleTestCase):
    def test_renders_all_counts(self):
        metrics = EvalReportMetrics(
            total_runs=100,
            pass_count=80,
            fail_count=18,
            na_count=2,
            pass_rate=81.63,
            period_start="2026-04-08T14:00:00+00:00",
            period_end="2026-04-08T15:00:00+00:00",
        )
        html = _render_metrics_block_html(metrics)
        self.assertIn("100", html)  # total_runs
        self.assertIn("80", html)  # pass_count
        self.assertIn("18", html)  # fail_count
        self.assertIn("2", html)  # na_count
        self.assertIn("81.63%", html)
        self.assertIn("Apr 08, 2026 14:00 UTC", html)

    def test_renders_delta_up(self):
        metrics = EvalReportMetrics(total_runs=10, pass_count=9, pass_rate=90.0, previous_pass_rate=80.0)
        html = _render_metrics_block_html(metrics)
        self.assertIn("▲", html)
        self.assertIn("10.00pp", html)

    def test_renders_delta_down(self):
        metrics = EvalReportMetrics(total_runs=10, pass_count=5, pass_rate=50.0, previous_pass_rate=80.0)
        html = _render_metrics_block_html(metrics)
        self.assertIn("▼", html)
        self.assertIn("30.00pp", html)

    def test_no_delta_when_previous_is_none(self):
        metrics = EvalReportMetrics(total_runs=10, pass_count=9, pass_rate=90.0, previous_pass_rate=None)
        html = _render_metrics_block_html(metrics)
        self.assertNotIn("▲", html)
        self.assertNotIn("▼", html)
        self.assertNotIn("pp vs previous", html)


class TestDeliverReport(SimpleTestCase):
    """End-to-end tests for deliver_report — mocks the email+slack sub-functions."""

    def _make_v2_content_dict(self, title: str = "A nice punchline") -> dict:
        """Build an EvalReportContent dict in v2 shape."""
        return EvalReportContent(
            title=title,
            sections=[ReportSection(title="Summary", content="All good.")],
            citations=[Citation(generation_id="g", trace_id="t", reason="example")],
            metrics=EvalReportMetrics(total_runs=10, pass_count=9, pass_rate=90.0),
        ).to_dict()

    def _make_report_run(self):
        run = MagicMock()
        run.content = self._make_v2_content_dict()
        run.period_start = MagicMock(isoformat=MagicMock(return_value="2026-03-01T00:00:00+00:00"))
        run.period_end = MagicMock(isoformat=MagicMock(return_value="2026-03-02T00:00:00+00:00"))
        run.report_id = "report-id"
        run.id = "run-id"
        return run

    def _make_report(self, targets):
        report = MagicMock()
        report.evaluation.name = "Test Eval"
        report.evaluation.id = "eval-id"
        report.team.id = 1
        report.team_id = 1
        report.delivery_targets = targets
        return report

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_deliver_report_calls_email(self, mock_report_qs, mock_run_qs, _mock_slack, mock_email):
        targets = [{"type": "email", "value": "test@example.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = []

        deliver_report("report-id", "run-id")

        mock_email.assert_called_once()
        self.assertEqual(run.delivery_status, "delivered")

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_deliver_report_handles_failures(self, mock_report_qs, mock_run_qs, _mock_slack, mock_email):
        targets = [{"type": "email", "value": "test@example.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = ["send failed"]

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

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_comma_separated_emails_all_fail_marks_failed(self, mock_report_qs, mock_run_qs, _mock_slack, mock_email):
        # Regression: a single email target with N comma-separated addresses can produce
        # N errors. all_failed must compare errors against delivery attempts, not target count.
        targets = [{"type": "email", "value": "a@x.com, b@x.com, c@x.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = ["fail a", "fail b", "fail c"]

        with self.assertRaises(RuntimeError):
            deliver_report("report-id", "run-id")

        self.assertEqual(run.delivery_status, "failed")

    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_email_report")
    @patch("posthog.temporal.llm_analytics.eval_reports.delivery.deliver_slack_report")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReportRun.objects")
    @patch("products.llm_analytics.backend.models.evaluation_reports.EvaluationReport.objects")
    def test_comma_separated_emails_some_fail_marks_partial(self, mock_report_qs, mock_run_qs, _mock_slack, mock_email):
        # Two of three addresses fail — should be partial_failure, not failed.
        targets = [{"type": "email", "value": "a@x.com, b@x.com, c@x.com"}]
        report = self._make_report(targets)
        run = self._make_report_run()

        mock_report_qs.select_related.return_value.get.return_value = report
        mock_run_qs.get.return_value = run
        mock_email.return_value = ["fail a", "fail b"]

        deliver_report("report-id", "run-id")

        self.assertEqual(run.delivery_status, "partial_failure")
