from typing import Any

from posthog.test.base import TestMigrations

FILTERS = {"serviceNames": ["api"], "severityLevels": ["error"]}


class TestThresholdIntoSourceConfig(TestMigrations):
    app = "alerts_platform"
    migrate_from = "0004_threshold_fields_nullable"
    migrate_to = "0005_threshold_into_source_config"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Configuration = apps.get_model("alerts_platform", "PlatformAlertConfiguration")

        def make(source_config: dict[str, Any]) -> Any:
            return Configuration.objects.create(
                team_id=self.team.id,
                name="API errors",
                source_kind="logs",
                source_config=source_config,
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=5,
            )

        self.copied = make(FILTERS).id
        self.already_moved = make({**FILTERS, "condition": {"threshold_count": 99}}).id

    def test_the_bound_moves_into_source_config_beside_the_filters(self) -> None:
        Configuration = self.apps.get_model("alerts_platform", "PlatformAlertConfiguration")  # type: ignore[union-attr]

        assert Configuration.objects.get(id=self.copied).source_config == {
            **FILTERS,
            "condition": {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5},
        }
        assert Configuration.objects.get(id=self.already_moved).source_config["condition"] == {"threshold_count": 99}
