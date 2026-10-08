from posthog.test.base import BaseTest

from posthog.temporal.ai.anomaly_investigation.notebook import NotebookRenderContext, build_investigation_markdown
from posthog.temporal.ai.anomaly_investigation.report import InvestigationHypothesis, InvestigationReport

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


class TestAnomalyInvestigationNotebook(BaseTest):
    def _make_context(self, report: InvestigationReport) -> NotebookRenderContext:
        insight = Insight.objects.create(team=self.team, name="pageviews/day")
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=insight,
            name="pageview spike",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
        )
        alert_check = AlertCheck.objects.create(
            alert_configuration=alert,
            calculated_value=123.0,
            triggered_dates=["2024-06-01", "2024-06-02"],
            interval="day",
        )
        return NotebookRenderContext(alert=alert, alert_check=alert_check, insight=insight, report=report)

    def test_builds_markdown_the_cell_tools_accept(self) -> None:
        report = InvestigationReport(
            verdict="true_positive",
            metric_meaning="Unique users who loaded a page under /pricing each day.",
            summary="Traffic doubled after a marketing campaign launch.",
            hypotheses=[
                InvestigationHypothesis(
                    title="Marketing launch",
                    rationale="A campaign started on 2024-06-01 matching the spike window.",
                    evidence=[
                        "Campaign ID 42 launched at 2024-06-01 08:00",
                        "Referrer share from utm_source=x grew 4x",
                    ],
                ),
            ],
            recommendations=["Confirm the spike with the marketing team.", "Hold further alerting for 24h."],
            tool_calls_used=3,
        )
        ctx = self._make_context(report)
        markdown = build_investigation_markdown(ctx)

        assert "## Verdict" in markdown
        assert "## What this metric measures" in markdown
        assert "## Hypotheses" in markdown
        assert "## Recommendations" in markdown
        assert "### Run details" in markdown
        assert "- Campaign ID 42 launched at 2024-06-01 08:00" in markdown

        # The source insight stays live through a SavedInsightNode Query component.
        assert '<Query title="pageviews/day"' in markdown
        assert f'query={{{{"kind":"SavedInsightNode","shortId":"{ctx.insight.short_id}"}}}}' in markdown

    def test_handles_inconclusive_verdict_with_empty_sections(self) -> None:
        report = InvestigationReport(
            verdict="inconclusive",
            summary="Not enough recent data.",
            hypotheses=[],
            recommendations=[],
            tool_calls_used=0,
        )
        markdown = build_investigation_markdown(self._make_context(report))

        assert "## Hypotheses" not in markdown
        assert "## Recommendations" not in markdown
        assert "## What this metric measures" not in markdown
        assert "## Verdict" in markdown
