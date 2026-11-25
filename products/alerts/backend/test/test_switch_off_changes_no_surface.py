from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.core.management import call_command

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval
from posthog.tasks.alerts.utils import _thresholds_drawn_on_chart

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.facade.api import (
    alert_inventory,
    enabled_alert_insight_ids,
    enabled_alerts_created_by,
    get_alert_team_id,
    insight_ids_with_alerts,
    insight_ids_with_enabled_alerts,
    list_enabled_alerts,
    search_insight_alerts,
    snooze_alert_from_slack,
)
from products.alerts.backend.llm_detector_limits import count_enabled_llm_alerts
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_firing_signal import _evaluated_alert
from products.alerts.backend.platform_hooks import insight_alert_creator, insight_alert_viewer
from products.alerts.backend.platform_insight_alert import investigated_alert
from products.alerts.backend.test.insight_alerts import create_insight_alert, move_to_platform
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _switch_off(team_id: int) -> None:
    call_command("switch_off_legacy_insight_alert_rows", "--team-id", str(team_id), "--apply", stdout=None)


def _delete_rows(team_id: int) -> None:
    AlertConfiguration.objects.filter(team_id=team_id).delete()


def _without_threshold_ids(shown: Any) -> Any:
    if isinstance(shown, list):
        return [_without_threshold_ids(item) for item in shown]
    if isinstance(shown, dict):
        return {
            key: {k: v for k, v in value.items() if k != "id"}
            if key == "threshold" and isinstance(value, dict)
            else _without_threshold_ids(value)
            for key, value in shown.items()
        }
    return shown


def _enabled(alert: AlertConfiguration | None) -> bool | None:
    return alert.enabled if alert else None


class TestSwitchOffChangesNoInsightSurface(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.traveller = time_machine.travel(NOW, tick=False)
        clock = self.traveller.start()
        self.addCleanup(self.traveller.stop)
        self.alert = create_insight_alert(self.team, created_by=self.user, next_check_at=NOW + timedelta(hours=1))
        # Apart in time, so rows and copies list in the same order.
        clock.shift(timedelta(minutes=1))
        self.real_time = create_insight_alert(
            self.team,
            created_by=self.user,
            name="real time",
            calculation_interval=AlertCalculationInterval.REAL_TIME.value,
        )
        clock.shift(timedelta(minutes=1))
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
        dashboard = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "dashboard"}).json()
        tiled = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{self.alert.insight_id}/", {"dashboards": [dashboard["id"]]}
        )
        assert tiled.status_code == status.HTTP_200_OK, tiled.content
        self.dashboard_url = f"/api/projects/{self.team.id}/dashboards/{dashboard['id']}"

    def _get(self, path: str) -> Any:
        response = self.client.get(path)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _surfaces(self) -> dict[str, Any]:
        insight_id = self.alert.insight_id
        access = UserAccessControl(self.user, team=self.team)
        with team_scope(self.team.id):
            copy_id = platform_testing.copy_of(self.alert.id).id
            copy = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=copy_id
            )
            assert copy is not None
            return {
                "api list": _without_threshold_ids(self._get(f"{self.url}/")["results"]),
                "api retrieve": _without_threshold_ids(self._get(f"{self.url}/{self.alert.id}/")),
                "insight embed": _without_threshold_ids(
                    self._get(f"/api/projects/{self.team.id}/insights/{insight_id}/").get("alerts")
                ),
                "dashboard embed": _without_threshold_ids(
                    [tile["insight"]["alerts"] for tile in self._get(f"{self.dashboard_url}/")["tiles"]]
                ),
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
                "investigation loads by the copy's id": _enabled(investigated_alert(self.team.id, copy_id)),
                "firing signal loads": _enabled(_evaluated_alert(self.team.id, copy)),
                "creator": insight_alert_creator(team_id=self.team.id, alert_id=self.alert.id),
                "viewer": insight_alert_viewer(team_id=self.team.id, alert_id=self.alert.id, user_id=self.user.id),
                "slack team": get_alert_team_id(self.alert.id),
                "insight has an alert": insight_ids_with_alerts([insight_id]),
                "chart thresholds": sorted(drawn.name for drawn in _thresholds_drawn_on_chart(self.alert)),
                "real-time limit": AlertConfiguration._counted(self.team.id, active_real_time=True),
                "AI detector limit": count_enabled_llm_alerts(team_id=self.team.id),
            }

    @parameterized.expand(
        [
            ("switching_off", _switch_off, set()),
            # The thresholds endpoint lists `Threshold` rows, which move to the copies in their own step.
            ("deleting", _delete_rows, {"thresholds"}),
        ]
    )
    def test_retiring_the_rows_changes_no_surface(
        self, _name: str, retire: Callable[[int], None], not_moved_yet: set[str]
    ) -> None:
        before = self._surfaces()
        assert (before["chart thresholds"], before["AI detector limit"], before["slack team"]) == (
            ["ai sibling", "alert"],
            1,
            self.team.id,
        )

        retire(self.team.id)

        assert not AlertConfiguration.objects.filter(team_id=self.team.id, enabled=True).exists()
        after = self._surfaces()
        assert {name: after[name] for name in before if after[name] != before[name]} == {
            name: after[name] for name in not_moved_yet
        }

    @parameterized.expand([("switched_off", _switch_off), ("deleted", _delete_rows)])
    def test_an_alert_whose_row_is_retired_still_snoozes_and_edits_as_on(
        self, _name: str, retire: Callable[[int], None]
    ) -> None:
        retire(self.team.id)

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
        logged = ActivityLog.objects.filter(
            team_id=self.team.id, scope="AlertConfiguration", item_id=str(self.alert.id), activity="updated"
        )
        assert sorted(change["field"] for row in logged for change in (row.detail or {})["changes"]) == [
            "name",
            "snoozed_until",
        ]

    @parameterized.expand([("switched_off", _switch_off), ("deleted", _delete_rows)])
    def test_an_alert_whose_row_is_retired_still_deletes(self, _name: str, retire: Callable[[int], None]) -> None:
        with team_scope(self.team.id):
            copy_id = platform_testing.copy_of(self.alert.id).id
        retire(self.team.id)

        response = self.client.delete(f"{self.url}/{self.alert.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
        assert self.client.get(f"{self.url}/{self.alert.id}/").status_code == status.HTTP_404_NOT_FOUND
        with team_scope(self.team.id):
            gone = get_configuration(
                team_id=self.team.id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=copy_id
            )
        assert gone is None
