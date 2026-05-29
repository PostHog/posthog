from posthog.temporal.ai.pulse.types import DetectChangesInputs, EnrichedFinding, Finding, MetricDescriptor


def _descriptor() -> MetricDescriptor:
    return MetricDescriptor(source="top_event", source_id=1, label="$pageview", query={"kind": "TrendsQuery"})


class TestPulseDTOFields:
    def test_finding_carries_impact_and_robust_z(self):
        f = Finding(
            descriptor=_descriptor(),
            current_value=50.0,
            baseline_value=100.0,
            change_pct=-0.5,
            impact=5.0,
            robust_z=4.2,
        )
        assert f.impact == 5.0
        assert f.robust_z == 4.2
        assert not hasattr(f, "z_score")

    def test_enriched_finding_carries_impact_and_robust_z(self):
        ef = EnrichedFinding(
            descriptor=_descriptor(),
            current_value=50.0,
            baseline_value=100.0,
            change_pct=-0.5,
            impact=5.0,
            robust_z=4.2,
            narrative="x",
        )
        assert ef.impact == 5.0
        assert ef.robust_z == 4.2

    def test_detect_inputs_uses_robust_z_threshold(self):
        di = DetectChangesInputs(team_id=1, candidates=[], robust_z_threshold=3.0, min_change_pct=0.25)
        assert di.robust_z_threshold == 3.0
        assert not hasattr(di, "z_threshold")
