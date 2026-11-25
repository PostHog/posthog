from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.core.management import call_command

from rest_framework import status

from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.utils import _thresholds_drawn_on_chart

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.facade.api import (
    alert_inventory,
    enabled_alert_insight_ids,
    enabled_alerts_created_by,
    insight_ids_with_enabled_alerts,
    list_enabled_alerts,
    search_insight_alerts,
    snooze_alert_from_slack,
)
from products.alerts.backend.llm_detector_limits import count_enabled_llm_alerts
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_insight_alert import investigated_alert, legacy_alert
from products.alerts.backend.test.insight_alerts import create_insight_alert, move_to_platform
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _switch_off(team_id: int) -> None:
    call_command("switch_off_legacy_insight_alert_rows", "--team-id", str(team_id), "--apply", stdout=None)


def _enabled(alert: AlertConfiguration | None) -> bool | None:
    return alert.enabled if alert else None


class TestSwitchOffChangesNoInsightSurface(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.traveller = time_machine.travel(NOW, tick=False)
        self.traveller.start()
        self.addCleanup(self.traveller.stop)
        self.alert = create_insight_alert(self.team, created_by=self.user, next_check_at=NOW + timedelta(hours=1))
        self.real_time = create_insight_alert(
            self.team,
            created_by=self.user,
            name="real time",
            calculation_interval=AlertCalculationInterval.REAL_TIME.value,
        )
        # On the same insight, so the chart has a threshold besides the alert's own, and an AI detector,
        # so the AI limit counts something that a switch-off could drop.
        self.ai_sibling = create_insight_alert(
            self.team,
            created_by=self.user,
            name="ai sibling",
            insight=self.alert.insight,
            detector_config={"type": "llm"},
        )
        for alert in (self.alert, self.real_time, self.ai_sibling):
            move_to_platform(alert, at=NOW - timedelta(days=10))
        self.url = f"/api/projects/{self.team.id}/alerts"

    def _get(self, path: str) -> Any:
        response = self.client.get(path)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _surfaces(self) -> dict[str, Any]:
        insight_id = self.alert.insight_id
        access = UserAccessControl(self.user, team=self.team)
        with team_scope(self.team.id):
            return {
                "api list": self._get(f"{self.url}/")["results"],
                "api retrieve": self._get(f"{self.url}/{self.alert.id}/"),
                "insight embed": self._get(f"/api/projects/{self.team.id}/insights/{insight_id}/").get("alerts"),
                "thresholds": self._get(f"/api/projects/{self.team.id}/insights/{insight_id}/thresholds/"),
                "today enabled": [a.id for a in list_enabled_alerts(self.team, self.user, limit=10)],
                "insights with enabled alerts": enabled_alert_insight_ids(team_ids=[self.team.id]),
                "insight has enabled alert": insight_ids_with_enabled_alerts(
                    team_id=self.team.id, insight_ids=[insight_id]
                ),
                "offboarding": sorted(
                    str(a.id) for a in enabled_alerts_created_by(team_ids=[self.team.id], user_id=self.user.id)
                ),
                "scout inventory": alert_inventory(team_id=self.team.id, recent_limit=5),
                "max search": search_insight_alerts(
                    project_id=self.team.project_id, query=None, access_control=access, limit=10
                ),
                "investigation loads": _enabled(investigated_alert(self.team.id, self.alert.id)),
                "firing signal loads": _enabled(legacy_alert(team_id=self.team.id, alert_id=self.alert.id)),
                "chart thresholds": sorted(drawn.name for drawn in _thresholds_drawn_on_chart(self.alert)),
                "real-time limit": AlertConfiguration._counted(self.team.id, active_real_time=True),
                "AI detector limit": count_enabled_llm_alerts(team_id=self.team.id),
            }

    def test_switching_off_the_rows_changes_no_surface(self) -> None:
        before = self._surfaces()
        assert (before["chart thresholds"], before["AI detector limit"]) == (["ai sibling", "alert"], 1)

        _switch_off(self.team.id)

        assert not AlertConfiguration.objects.filter(team_id=self.team.id, enabled=True).exists()
        after = self._surfaces()
        assert {name: after[name] for name in before if after[name] != before[name]} == {}

    def test_a_switched_off_alert_still_snoozes_and_edits_as_on(self) -> None:
        _switch_off(self.team.id)

        assert snooze_alert_from_slack(self.alert.id, user=self.user, duration="1h") == "snoozed"
        response = self.client.patch(f"{self.url}/{self.alert.id}/", {"name": "renamed"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        with team_scope(self.team.id):
            copies = [
                get_configuration(
                    team_id=self.team.id,
                    source_kinds=[SourceKind.INSIGHT.value],
                    configuration_id=platform_testing.copy_of(alert.id).id,
                )
                for alert in (self.alert, self.real_time)
            ]
        assert (response.json()["enabled"], [copy.enabled for copy in copies if copy]) == (True, [True, True])
