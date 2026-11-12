from io import StringIO
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.core.management import call_command
from django.db.models.signals import pre_delete

from parameterized import parameterized

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.activity_logging import delete_platform_shadow_copy
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts.backend.platform_alert_backfill import (
    backfill_platform_insight_alert_configurations,
    disable_platform_insight_alert_configurations,
    follow_insight_alert,
)
from products.alerts.backend.platform_insight_alert import INSIGHT_ROW_SETTINGS
from products.alerts_platform.backend.facade.api import list_configurations
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.product_analytics.backend.facade.models import Insight

THRESHOLD = {"type": "absolute", "bounds": {"upper": 100.0}}


class TestPlatformInsightAlertBackfill(APIBaseTest):
    def _alert(self, team: Team | None = None, **overrides: Any) -> AlertConfiguration:
        team = team or self.team
        insight = Insight.objects.create(
            team=team,
            name="insight",
            query=TrendsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
            ).model_dump(),
        )
        threshold = Threshold.objects.create(team=team, insight=insight, configuration=THRESHOLD)
        fields: dict[str, Any] = {
            "team": team,
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
        daily = self._alert(
            schedule_start_time="09:30",
            created_by=self.user,
            skip_weekend=True,
            evaluation_delay_intervals=2,
            investigation_agent_enabled=True,
            investigation_inconclusive_action="suppress",
        )
        detector = self._alert(detector_config={"type": "zscore"})
        ai_detector = self._alert(detector_config={"type": "llm"})
        unparseable = self._alert(schedule_start_time="25:99")

        counts = backfill_platform_insight_alert_configurations(team_id=self.team.id)
        assert (counts.created, counts.skipped, counts.failed) == (5, 1, 1)
        assert ai_detector.id not in self._copies()

        call_command(
            "backfill_platform_insight_alert_configurations",
            team_id=self.team.id,
            include_ai_detector=True,
            stdout=StringIO(),
        )
        again = backfill_platform_insight_alert_configurations(team_id=self.team.id, include_ai_detector=True)

        assert (again.created, again.updated) == (0, 6)
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
        assert {key: copies[daily.id].source_config[key] for key in INSIGHT_ROW_SETTINGS} == {
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "skip_weekend": True,
            "evaluation_delay_intervals": 2,
            "investigation_agent_enabled": True,
            "investigation_gates_notifications": False,
            "investigation_inconclusive_action": "suppress",
        }
        assert copies[detector.id].source_config["condition"]["detector"] == {"type": "zscore"}
        assert (copies[daily.id].created_by_id, copies[detector.id].created_by_id) == (self.user.id, None)

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

    @parameterized.expand(
        [
            ("a_team_on_the_platform", "running", False, None, "renamed"),
            ("insight_off_the_platform", "nowhere", False, None, None),
            ("a_team_new_to_the_platform", "elsewhere", False, None, "renamed"),
            ("a_team_with_only_disabled_copies", "disabled_copies", False, None, "renamed"),
            ("a_team_an_operator_switched_off", "switched_off", False, None, None),
            ("a_team_switched_off_with_only_disabled_copies", "switched_off_disabled_copies", False, None, None),
            ("an_ai_alert", "running", False, {"type": "llm"}, None),
            ("an_alert_switched_to_ai_after_its_copy", "running", True, {"type": "llm"}, "alert"),
        ]
    )
    def test_a_created_or_reenabled_alert_follows_its_team_onto_the_platform(
        self,
        _name: str,
        team_state: str,
        copied_before: bool,
        detector: dict[str, str] | None,
        copy_name: str | None,
    ) -> None:
        if team_state != "nowhere":
            other_team = Team.objects.create(organization=self.organization, name="other")
            self._alert(team=other_team)
            backfill_platform_insight_alert_configurations(team_id=other_team.id)
        if team_state in ("running", "switched_off"):
            self._alert()
            backfill_platform_insight_alert_configurations(team_id=self.team.id)
        if team_state == "switched_off":
            disable_platform_insight_alert_configurations(team_id=self.team.id)
        if team_state in ("disabled_copies", "switched_off_disabled_copies"):
            self._alert(enabled=False)
            backfill_platform_insight_alert_configurations(team_id=self.team.id)
        if team_state == "switched_off_disabled_copies":
            disable_platform_insight_alert_configurations(team_id=self.team.id)
        created = self._alert()
        if copied_before:
            backfill_platform_insight_alert_configurations(alert_ids=[created.id])
        created.name = "renamed"
        created.detector_config = detector
        created.save()

        follow_insight_alert(created)

        copy = self._copies().get(created.id)
        assert (copy.name if copy else None) == copy_name

    @parameterized.expand([("with_the_alert",), ("with_its_insight",)])
    def test_deleting_an_alert_deletes_its_copy_and_no_other(self, route: str) -> None:
        deleted = self._alert()
        kept = self._alert()
        backfill_platform_insight_alert_configurations(team_id=self.team.id)

        with self.captureOnCommitCallbacks(execute=True):
            if route == "with_the_alert":
                deleted.delete()
            else:
                deleted.insight.delete()

        assert set(self._copies()) == {kept.id}

    def test_the_cleanup_command_deletes_only_copies_whose_alert_is_gone(self) -> None:
        orphaned = self._alert()
        orphaned_id = orphaned.id
        kept = self._alert()
        backfill_platform_insight_alert_configurations(team_id=self.team.id)
        pre_delete.disconnect(delete_platform_shadow_copy, sender=AlertConfiguration)
        try:
            orphaned.delete()
        finally:
            pre_delete.connect(delete_platform_shadow_copy, sender=AlertConfiguration)

        dry_run = StringIO()
        call_command("delete_orphaned_platform_insight_alert_copies", dry_run=True, stdout=dry_run)
        assert set(self._copies()) == {orphaned_id, kept.id}
        call_command("delete_orphaned_platform_insight_alert_copies", stdout=StringIO())

        assert "Would delete 1 " in dry_run.getvalue()
        assert set(self._copies()) == {kept.id}
