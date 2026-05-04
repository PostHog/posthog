from posthog.test.base import BaseTest

from posthog.models import Insight
from posthog.models.alert import AlertCheck, AlertConfiguration
from posthog.temporal.ai.anomaly_investigation.notebook import NotebookRenderContext, build_investigation_notebook
from posthog.temporal.ai.anomaly_investigation.report import InvestigationHypothesis, InvestigationReport


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

    def test_builds_well_formed_tiptap_doc(self) -> None:
        report = InvestigationReport(
            verdict="true_positive",
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
        doc = build_investigation_notebook(self._make_context(report))

        assert doc["type"] == "doc"
        headings = [node for node in doc["content"] if node.get("type") == "heading"]
        heading_texts = [node["content"][0]["text"] for node in headings if node.get("content")]
        assert any("Verdict" == t for t in heading_texts)
        assert any("Hypotheses" == t for t in heading_texts)
        assert any("Recommendations" == t for t in heading_texts)

        # The saved insight node is present and uses the insight's short_id.
        ph_queries = [node for node in doc["content"] if node.get("type") == "ph-query"]
        assert len(ph_queries) == 1

    def test_handles_inconclusive_verdict_with_empty_sections(self) -> None:
        report = InvestigationReport(
            verdict="inconclusive",
            summary="Not enough recent data.",
            hypotheses=[],
            recommendations=[],
            tool_calls_used=0,
        )
        doc = build_investigation_notebook(self._make_context(report))
        # Recommendations and Hypotheses headings should be absent when lists are empty.
        heading_texts = [
            node["content"][0]["text"]
            for node in doc["content"]
            if node.get("type") == "heading" and node.get("content")
        ]
        assert "Hypotheses" not in heading_texts
        assert "Recommendations" not in heading_texts
        assert "Verdict" in heading_texts
