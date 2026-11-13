from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_cutover import cut_over_team
from products.alerts.backend.test.insight_alerts import create_insight_alert

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


class TestInsightLegacyConfigDrift(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = create_insight_alert(self.team, next_check_at=NOW + timedelta(minutes=3))
        (result,) = cut_over_team(self.team.id, now=NOW)
        assert result.skipped is None

    def _report(self) -> tuple[str, CommandError | None]:
        out = StringIO()
        try:
            call_command("report_legacy_config_drift", source=["insight"], team_id=self.team.id, stdout=out)
        except CommandError as error:
            return out.getvalue(), error
        return out.getvalue(), None

    def test_a_copy_that_matches_its_row_reports_no_drift(self) -> None:
        output, error = self._report()

        assert error is None
        assert "Compared 1 platform-owned alerts across insight: 0 differ" in output

    def test_an_ended_snooze_on_one_side_is_not_drift(self) -> None:
        AlertConfiguration.objects.filter(id=self.alert.id).update(snoozed_until=timezone.now() - timedelta(hours=1))

        _, error = self._report()

        assert error is None

    @parameterized.expand(
        [
            ("name", {"name": "renamed"}, ["name"]),
            ("enabled", {"enabled": False}, ["enabled"]),
            (
                "cadence",
                {"calculation_interval": AlertCalculationInterval.WEEKLY.value},
                ["check_interval_minutes", "recurrence_unit"],
            ),
            ("snooze", {"snoozed_until": timezone.now() + timedelta(days=1)}, ["snooze_until"]),
            ("schedule_restriction", {"schedule_restriction": {"blocked_windows": []}}, ["schedule_restriction"]),
            ("condition", {"condition": {"type": "relative_increase"}}, ["source_config.condition.comparison"]),
            (
                "config",
                {"config": {"type": "TrendsAlertConfig", "series_index": 1}},
                ["source_config.config.series_index"],
            ),
            ("skip_weekend", {"skip_weekend": True}, ["source_config.skip_weekend"]),
            ("evaluation_delay", {"evaluation_delay_intervals": 2}, ["source_config.evaluation_delay_intervals"]),
            (
                "investigation",
                {"investigation_agent_enabled": True},
                ["source_config.investigation_agent_enabled"],
            ),
        ]
    )
    def test_an_edit_the_copy_missed_is_reported_per_setting(
        self, _name: str, row_change: dict[str, Any], settings: list[str]
    ) -> None:
        AlertConfiguration.objects.filter(id=self.alert.id).update(**row_change)

        output, error = self._report()

        assert error is not None and error.returncode == 1
        for setting in settings:
            assert f"team={self.team.id} source=insight setting={setting} alerts=1 sample=[{self.alert.id}]" in output
        assert output.count("setting=") == len(settings)

    def test_a_threshold_the_copy_missed_is_reported(self) -> None:
        assert self.alert.threshold_id is not None
        Threshold.objects.filter(id=self.alert.threshold_id).update(
            configuration={"type": "absolute", "bounds": {"upper": 5.0}}
        )

        output, error = self._report()

        assert error is not None
        assert "setting=source_config.condition.threshold alerts=1" in output
