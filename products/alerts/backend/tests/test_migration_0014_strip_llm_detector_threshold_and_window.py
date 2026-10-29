from typing import Any

from posthog.test.base import TestMigrations

ZSCORE = {"type": "zscore", "threshold": 0.95, "window": 30}


class TestStripLLMDetectorThresholdAndWindow(TestMigrations):
    app = "alerts"
    migrate_from = "0013_alertconfiguration_owner"
    migrate_to = "0014_strip_llm_detector_threshold_and_window"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Insight = apps.get_model("product_analytics", "Insight")
        AlertConfiguration = apps.get_model("alerts", "AlertConfiguration")
        insight = Insight.objects.create(team_id=self.team.id)

        def make(detector_config: dict[str, Any] | None) -> Any:
            return AlertConfiguration.objects.create(
                team_id=self.team.id, insight=insight, detector_config=detector_config
            ).id

        self.llm = make({"type": "llm", "threshold": 0.7, "window": 90, "instructions": "Only drops"})
        self.zscore = make(ZSCORE)
        self.threshold_alert = make(None)

    def test_only_llm_configs_lose_threshold_and_window(self) -> None:
        AlertConfiguration = self.apps.get_model("alerts", "AlertConfiguration")  # type: ignore[union-attr]

        assert AlertConfiguration.objects.get(id=self.llm).detector_config == {
            "type": "llm",
            "instructions": "Only drops",
        }
        assert AlertConfiguration.objects.get(id=self.zscore).detector_config == ZSCORE
        assert AlertConfiguration.objects.get(id=self.threshold_alert).detector_config is None
