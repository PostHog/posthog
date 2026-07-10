from types import SimpleNamespace

from posthog.temporal.ai.anomaly_investigation.report import InvestigationHypothesis, InvestigationReport
from posthog.temporal.ai.anomaly_investigation.workflow import (
    _build_investigation_signal_extra,
    _build_signal_description,
)

from products.signals.backend.contracts import AnomalyInvestigationSignalExtra


def _report(**overrides) -> InvestigationReport:
    defaults: dict = {
        "verdict": "true_positive",
        "summary": "Signups fell 40% after the deploy.",
        "hypotheses": [
            InvestigationHypothesis(title="Broken form", rationale="JS error on submit", evidence=["exception spike"])
        ],
        "recommendations": ["Roll back the deploy"],
        "tool_calls_used": 3,
    }
    defaults.update(overrides)
    return InvestigationReport(**defaults)


class TestBuildInvestigationSignalExtra:
    def test_extra_matches_contract_schema(self) -> None:
        extra = _build_investigation_signal_extra(
            alert=SimpleNamespace(id="alert-1", name="Signups dropped"),
            alert_check=SimpleNamespace(id="check-1", triggered_dates=["2026-07-09"]),
            insight=SimpleNamespace(name="Daily signups", short_id="abc123"),
            detector_type="zscore",
            report=_report(),
            notebook_short_id="nb123",
        )

        # Round-trips through the schema emit_signal validates against: if the builder's keys drift
        # from AnomalyInvestigationSignalExtra, emit_signal would silently reject the signal in prod.
        AnomalyInvestigationSignalExtra.model_validate(extra)
        assert extra["verdict"] == "true_positive"
        assert extra["hypotheses"][0]["title"] == "Broken form"

    def test_optional_fields_omitted_when_absent(self) -> None:
        extra = _build_investigation_signal_extra(
            alert=SimpleNamespace(id="alert-1", name=""),
            alert_check=SimpleNamespace(id="check-1", triggered_dates=None),
            insight=SimpleNamespace(name=None, short_id=None),
            detector_type="threshold",
            report=_report(hypotheses=[], recommendations=[]),
            notebook_short_id=None,
        )

        AnomalyInvestigationSignalExtra.model_validate(extra)
        assert "insight_name" not in extra
        assert "insight_short_id" not in extra
        assert "triggered_dates" not in extra
        assert "notebook_short_id" not in extra
        assert extra["url"].endswith("/alerts")


class TestBuildSignalDescription:
    def test_leads_with_verdict_and_includes_findings(self) -> None:
        description = _build_signal_description(
            alert_name="Signups dropped",
            insight_name="Daily signups",
            report=_report(),
        )

        assert "verdict: true positive" in description
        assert "Signups fell 40% after the deploy." in description
        assert "- Broken form: JS error on submit" in description
        assert "- Roll back the deploy" in description
