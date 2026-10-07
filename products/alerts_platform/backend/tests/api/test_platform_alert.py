from datetime import UTC, datetime
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


class TestPlatformAlertAPI(APIBaseTest):
    def _create_configuration(
        self,
        team: Team,
        name: str,
        legacy_configuration_id: UUID | None = None,
        source_kind: str = PlatformAlertConfiguration.SourceKind.LOGS,
    ) -> PlatformAlertConfiguration:
        with team_scope(team.id):
            return PlatformAlertConfiguration.objects.create(
                team=team,
                name=name,
                source_kind=source_kind,
                source_config={"service": "api"},
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
            alert = PlatformAlert.objects.create(
                team=self.team,
                configuration=configuration,
                grouping_key="checkout",
                state=PlatformAlert.State.FIRING,
                firing_started_at=firing_started_at,
                last_notified_at=firing_started_at,
            )
        list_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        results = list_response.json()["results"]
        assert [r["id"] for r in results] == [str(configuration.id)]
        assert results[0]["legacy_configuration_id"] == str(legacy_configuration_id)
        assert results[0]["alerts"] == [
            {
                "id": str(alert.id),
                "grouping_key": "checkout",
                "state": "firing",
                "firing_started_at": "2026-09-16T10:00:00Z",
                "last_notified_at": "2026-09-16T10:00:00Z",
                "snooze_until": None,
            }
        ]

    def test_a_child_environment_reads_its_parents_configurations(self) -> None:
        # The viewset resolves a child environment to its parent before reading, so a request
        # against the child sees the parent's rows rather than an empty project.
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors")
        child_environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")

        response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/{configuration.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(configuration.id)

    def test_another_teams_configuration_is_not_found(self) -> None:
        self._set_flag(True)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_configuration = self._create_configuration(other_team, "Other team errors")

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{other_configuration.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("logs_member_without_access", "logs", None, False),
            ("logs_key_without_scope", "logs", ["alert:read"], False),
            ("logs_key_with_scope", "logs", ["alert:read", "logs:read"], True),
            ("insight_key_with_scope", "insight", ["alert:read", "insight:read"], False),
        ]
    )
    def test_a_configuration_needs_read_access_to_its_source_product(
        self, _name: str, source_kind: str, key_scopes: list[str] | None, visible: bool
    ) -> None:
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors", source_kind=source_kind)
        if key_scopes is None:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            member = User.objects.create_and_join(self.organization, "alerts-only@posthog.com", "testtest")
            AccessControl.objects.create(
                team=self.team,
                resource=source_kind,
                resource_id=None,
                access_level="none",
                organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
            )
            self.client.force_login(member)
        else:
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        list_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/")
        retrieve_response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{configuration.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert [r["id"] for r in list_response.json()["results"]] == ([str(configuration.id)] if visible else [])
        expected_retrieve_status = status.HTTP_200_OK if visible else status.HTTP_404_NOT_FOUND
        assert retrieve_response.status_code == expected_retrieve_status, retrieve_response.json()

    def test_a_logs_denial_on_the_parent_survives_a_child_environment_url(self) -> None:
        # The rows are read from the parent, so the access check has to be read from the parent
        # too. Anchored on the URL's team instead, a deny written on the project is invisible to a
        # request that names one of its environments, and the parent's `source_config` filters are
        # exactly what the deny was protecting.
        self._set_flag(True)
        configuration = self._create_configuration(self.team, "API errors")
        child_environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "denied-logs@posthog.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="logs",
            resource_id=None,
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )
        self.client.force_login(member)

        list_response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/")
        retrieve_response = self.client.get(f"/api/projects/{child_environment.id}/platform_alerts/{configuration.id}/")

        assert list_response.status_code == status.HTTP_200_OK, list_response.json()
        assert [r["id"] for r in list_response.json()["results"]] == []
        assert retrieve_response.status_code == status.HTTP_404_NOT_FOUND, retrieve_response.json()

    def test_a_malformed_id_is_refused_rather_than_raising(self) -> None:
        self._set_flag(True)

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/not-a-uuid/")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_two_pages_cover_every_row_once(self) -> None:
        # `list` asks the facade for a slice and then hands that slice to the paginator. An offset
        # applied by both would skip rows at the page boundary, which a single-page test cannot see.
        self._set_flag(True)
        created = {str(self._create_configuration(self.team, f"Alert {index}").id) for index in range(3)}
        url = f"/api/projects/{self.team.id}/platform_alerts/"

        first = self.client.get(f"{url}?limit=2").json()
        second = self.client.get(f"{url}?limit=2&offset=2").json()

        first_ids = [row["id"] for row in first["results"]]
        second_ids = [row["id"] for row in second["results"]]
        assert first["count"] == 3
        assert len(first_ids) == 2
        assert len(second_ids) == 1
        assert set(first_ids).isdisjoint(second_ids)
        assert set(first_ids) | set(second_ids) == created

    def test_a_page_costs_the_same_queries_however_many_rows_it_holds(self) -> None:
        # A filter added to the prefetched relation would bypass the cache and cost a query per
        # configuration, which no assertion on the response body would notice.
        self._set_flag(True)
        for index in range(4):
            self._create_configuration(self.team, f"Alert {index}")
        url = f"/api/projects/{self.team.id}/platform_alerts/"

        self.client.get(f"{url}?limit=1")  # The first request of a test warms caches the rest reuse.

        assert self._queries_for(f"{url}?limit=4") == self._queries_for(f"{url}?limit=1")

    def _queries_for(self, url: str) -> int:
        with CaptureQueriesContext(connection) as captured:
            self.client.get(url)
        return len(captured)
