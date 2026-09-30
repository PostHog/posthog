from datetime import UTC, datetime
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration


class TestPlatformAlertAPI(APIBaseTest):
    def _create_configuration(
        self, team: Team, name: str, legacy_configuration_id: UUID | None = None
    ) -> PlatformAlertConfiguration:
        with team_scope(team.id):
            return PlatformAlertConfiguration.objects.create(
                team=team,
                name=name,
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={"service": "api"},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=10,
                legacy_configuration_id=legacy_configuration_id,
            )

    def _set_flag(self, enabled: bool) -> None:
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=enabled))

    @parameterized.expand([("list", False), ("retrieve", True)])
    def test_flag_off_blocks_access(self, _name: str, with_id: bool) -> None:
        self._set_flag(False)
        configuration = self._create_configuration(self.team, "API errors")
        url = f"/api/projects/{self.team.id}/platform_alerts/"
        if with_id:
            url += f"{configuration.id}/"

        response = self.client.get(url)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["code"] == "feature_flag_required"

    def test_list_returns_own_configurations_with_nested_alerts(self) -> None:
        self._set_flag(True)
        legacy_configuration_id = uuid4()
        configuration = self._create_configuration(self.team, "API errors", legacy_configuration_id)
        firing_started_at = datetime(2026, 9, 16, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            PlatformAlert.objects.create(
                team=self.team,
                configuration=configuration,
                grouping_key="checkout",
                state=PlatformAlert.State.FIRING,
                firing_started_at=firing_started_at,
                last_notified_at=firing_started_at,
            )
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_configuration = self._create_configuration(other_team, "Other team errors")

        list_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/")
        other_retrieve_response = self.client.get(
            f"/api/projects/{self.team.id}/platform_alerts/{other_configuration.id}/"
        )

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        results = list_response.json()["results"]
        assert [r["id"] for r in results] == [str(configuration.id)]
        assert results[0]["legacy_configuration_id"] == str(legacy_configuration_id)
        assert results[0]["alerts"] == [
            {
                "id": results[0]["alerts"][0]["id"],
                "grouping_key": "checkout",
                "state": "firing",
                "firing_started_at": "2026-09-16T10:00:00Z",
                "last_notified_at": "2026-09-16T10:00:00Z",
                "snooze_until": None,
            }
        ]
        assert other_retrieve_response.status_code == status.HTTP_404_NOT_FOUND
