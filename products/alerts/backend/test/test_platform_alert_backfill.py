from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_alert_backfill import (
    backfill_platform_insight_alert_configurations,
    disable_platform_insight_alert_configurations,
    follow_insight_alert,
)
from products.alerts_platform.backend.facade.api import list_configurations
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.product_analytics.backend.facade.models import Insight

THRESHOLD = {"type": "absolute", "bounds": {"upper": 100.0}}


class TestPlatformInsightAlertBackfill(APIBaseTest):
    def _alert(self, **overrides: Any) -> AlertConfiguration:
        insight = Insight.objects.create(
            team=self.team,
            name="insight",
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            ).model_dump(),
        )
        threshold = Threshold.objects.create(team=self.team, insight=insight, configuration=THRESHOLD)
        fields: dict[str, Any] = {
            "team": self.team,
            "insight": insight,
            "name": "alert",
            "calculation_interval": AlertCalculationInterval.DAILY.value,
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "condition": {"type": "absolute_value"},
            "threshold": threshold,
        }
        fields.update(overrides)
        return AlertConfiguration.objects.create(**fields)

    def _copies(self) -> dict[Any, Any]:
        with team_scope(self.team.id):
            page = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], limit=10, offset=0
            )
        return {view.legacy_configuration_id: view for view in page.configurations}

    def test_every_alert_is_copied_on_its_recurrence(self) -> None:
        real_time = self._alert(calculation_interval=AlertCalculationInterval.REAL_TIME.value)
        quarter_hourly = self._alert(calculation_interval=AlertCalculationInterval.EVERY_15_MINUTES.value)
        hourly = self._alert(calculation_interval=AlertCalculationInterval.HOURLY.value, schedule_start_time="09:30")
        daily = self._alert(schedule_start_time="09:30")
        detector = self._alert(detector_config={"type": "zscore"})
        ai_detector = self._alert(detector_config={"type": "llm"})
        unparseable = self._alert(schedule_start_time="25:99")

        counts = backfill_platform_insight_alert_configurations(team_id=self.team.id)
        again = backfill_platform_insight_alert_configurations(team_id=self.team.id)

        assert (counts.created, counts.skipped, counts.failed, again.created, again.updated) == (6, 0, 1, 0, 6)
        copies = self._copies()
        assert unparseable.id not in copies
        assert {key: (v.check_interval_minutes, v.recurrence_unit, v.anchor_time) for key, v in copies.items()} == {
            real_time.id: (2, None, None),
            quarter_hourly.id: (15, None, None),
            hourly.id: (60, None, "09:30"),
            daily.id: (60 * 24, "day", "09:30"),
            detector.id: (60 * 24, "day", None),
            ai_detector.id: (60 * 24, "day", None),
        }
        assert copies[daily.id].source_config["condition"] == {
            "threshold": THRESHOLD,
            "comparison": {"type": "absolute_value"},
            "detector": None,
        }
        assert copies[detector.id].source_config["condition"]["detector"] == {"type": "zscore"}

    def test_a_sample_copies_the_same_alerts_on_every_run_and_widening_it_only_adds(self) -> None:
        inside = self._alert(id=UUID(int=5))
        outside = self._alert(id=UUID(int=50))

        backfill_platform_insight_alert_configurations(team_id=self.team.id, sample_percent=10)
        assert set(self._copies()) == {inside.id}

        backfill_platform_insight_alert_configurations(team_id=self.team.id, sample_percent=60)
        assert set(self._copies()) == {inside.id, outside.id}

    def test_named_alerts_are_the_only_ones_copied(self) -> None:
        named = self._alert()
        self._alert()

        backfill_platform_insight_alert_configurations(alert_ids=[named.id])

        assert set(self._copies()) == {named.id}

    def test_disabling_stops_every_copy_and_a_rerun_turns_them_back_on(self) -> None:
        self._alert()
        self._alert()
        backfill_platform_insight_alert_configurations(team_id=self.team.id)

        assert disable_platform_insight_alert_configurations(team_id=self.team.id) == 2
        assert {view.enabled for view in self._copies().values()} == {False}

        backfill_platform_insight_alert_configurations(team_id=self.team.id)
        assert {view.enabled for view in self._copies().values()} == {True}

    @parameterized.expand([("a_team_on_the_platform", True), ("a_team_off_the_platform", False)])
    def test_a_created_or_reenabled_alert_follows_its_team_onto_the_platform(self, _name: str, running: bool) -> None:
        if running:
            self._alert()
            backfill_platform_insight_alert_configurations(team_id=self.team.id)
        created = self._alert()

        follow_insight_alert(created)

        assert (created.id in self._copies()) is running
