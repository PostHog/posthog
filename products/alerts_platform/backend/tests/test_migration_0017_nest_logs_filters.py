from typing import Any

from posthog.test.base import TestMigrations

FILTERS = {"serviceNames": ["api"], "severityLevels": ["error"]}
CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}


class TestNestLogsFilters(TestMigrations):
    app = "alerts_platform"
    migrate_from = "0016_platformalertdeliverypath"
    migrate_to = "0017_nest_logs_filters"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Configuration = apps.get_model("alerts_platform", "PlatformAlertConfiguration")

        def make(source_kind: str, source_config: dict[str, Any]) -> Any:
            return Configuration.objects.create(
                team_id=self.team.id,
                name="API errors",
                source_kind=source_kind,
                source_config=source_config,
                check_interval_minutes=5,
                enabled=False,
            ).id

        self.flat = make("logs", {**FILTERS, "condition": CONDITION})
        self.no_condition = make("logs", FILTERS)
        self.nested = make("logs", {"filters": {"serviceNames": ["web"]}, "condition": CONDITION})
        self.insight = make("insight", {"insight_id": 7, "condition": {"comparison": {"type": "absolute"}}})

    def test_logs_filters_move_under_their_own_key(self) -> None:
        Configuration = self.apps.get_model("alerts_platform", "PlatformAlertConfiguration")  # type: ignore[union-attr]
        stored = {c.id: c.source_config for c in Configuration.objects.all()}

        assert stored[self.flat] == {"filters": FILTERS, "condition": CONDITION}
        assert stored[self.no_condition] == {"filters": FILTERS}
        assert stored[self.nested] == {"filters": {"serviceNames": ["web"]}, "condition": CONDITION}
        assert stored[self.insight] == {"insight_id": 7, "condition": {"comparison": {"type": "absolute"}}}
