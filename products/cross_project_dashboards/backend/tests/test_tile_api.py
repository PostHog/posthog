import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team

from products.access_control.backend.facade.api import AccessControl, Role, RoleMembership
from products.cross_project_dashboards.backend.models import CrossProjectDashboard, CrossProjectDashboardTile
from products.product_analytics.backend.facade.models import Insight


@patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
class TestCrossProjectDashboardTileAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.dashboard = CrossProjectDashboard.objects.create(
            organization=self.organization, name="Company overview", created_by=self.user
        )

    def _url(self, suffix: str = "") -> str:
        return f"/api/organizations/{self.organization.id}/cross_project_dashboards/{self.dashboard.id}/tiles/{suffix}"

    def _insight(self, name: str = "Signups") -> Insight:
        return Insight.objects.create(team=self.team, name=name)

    def test_adds_one_tile(self, _flag):
        insight = self._insight()
        response = self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": insight.pk}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["insight_id"] == insight.pk
        assert self.dashboard.tiles.filter(deleted=False).count() == 1

    def test_rejects_a_project_bound_filter_on_one_tile(self, _flag):
        insight = self._insight()
        response = self.client.post(
            self._url(),
            {
                "project_id": self.team.pk,
                "insight_id": insight.pk,
                "filters_overrides": {"properties": [{"type": "cohort", "key": "id", "value": 7}]},
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_allows_a_date_override_on_one_tile(self, _flag):
        insight = self._insight()
        response = self.client.post(
            self._url(),
            {"project_id": self.team.pk, "insight_id": insight.pk, "filters_overrides": {"date_from": "-7d"}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["filters_overrides"] == {"date_from": "-7d"}

    def test_adding_a_tile_leaves_existing_tiles_alone(self, _flag):
        first = self._insight("First")
        second = self._insight("Second")
        self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": first.pk}, format="json")

        self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": second.pk}, format="json")

        live = self.dashboard.tiles.filter(deleted=False).values_list("insight_id", flat=True)
        assert sorted(live) == sorted([first.pk, second.pk])

    def test_updates_one_tile_without_touching_others(self, _flag):
        first = self._insight("First")
        second = self._insight("Second")
        created = self.client.post(
            self._url(), {"project_id": self.team.pk, "insight_id": first.pk}, format="json"
        ).json()
        self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": second.pk}, format="json")

        response = self.client.patch(
            self._url(f"{created['id']}/"), {"layouts": {"sm": {"x": 1, "y": 2}}}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["layouts"] == {"sm": {"x": 1, "y": 2}}
        assert self.dashboard.tiles.filter(deleted=False).count() == 2

    def test_a_tile_cannot_be_repointed_at_another_insight(self, _flag):
        first = self._insight("First")
        other = self._insight("Other")
        created = self.client.post(
            self._url(), {"project_id": self.team.pk, "insight_id": first.pk}, format="json"
        ).json()

        self.client.patch(self._url(f"{created['id']}/"), {"insight_id": other.pk}, format="json")

        tile = CrossProjectDashboardTile.objects.get(id=created["id"])
        assert tile.insight_id == first.pk

    def test_deletes_one_tile_and_keeps_the_rest(self, _flag):
        first = self._insight("First")
        second = self._insight("Second")
        created = self.client.post(
            self._url(), {"project_id": self.team.pk, "insight_id": first.pk}, format="json"
        ).json()
        self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": second.pk}, format="json")

        response = self.client.delete(self._url(f"{created['id']}/"))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        live = list(self.dashboard.tiles.filter(deleted=False).values_list("insight_id", flat=True))
        assert live == [second.pk]

    def test_rejects_layouts_that_are_not_an_object(self, _flag):
        insight = self._insight()
        response = self.client.post(
            self._url(), {"project_id": self.team.pk, "insight_id": insight.pk, "layouts": []}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_rejects_a_tile_past_the_per_dashboard_ceiling(self, _flag):
        CrossProjectDashboardTile.objects.bulk_create(
            CrossProjectDashboardTile(
                dashboard=self.dashboard, organization=self.organization, project_id=self.team.pk, insight_id=n
            )
            for n in range(100)
        )
        insight = self._insight()

        response = self.client.post(self._url(), {"project_id": self.team.pk, "insight_id": insight.pk}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert self.dashboard.tiles.filter(deleted=False).count() == 100

    def test_rejects_an_insight_the_user_cannot_reach(self, _flag):
        response = self.client.post(self._url(), {"project_id": 999999, "insight_id": 1}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_deleted_dashboard_tiles_can_no_longer_be_read_or_edited(self, _flag):
        tile = CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard,
            organization=self.organization,
            project_id=self.team.pk,
            insight_id=self._insight().pk,
        )
        self.dashboard.deleted = True
        self.dashboard.save()

        assert self.client.get(self._url()).json()["results"] == []
        assert self.client.get(self._url(f"{tile.id}/")).status_code == status.HTTP_404_NOT_FOUND
        assert (
            self.client.patch(self._url(f"{tile.id}/"), {"color": "blue"}, format="json").status_code
            == status.HTTP_404_NOT_FOUND
        )

    def test_does_not_expose_another_organizations_tiles(self, _flag):
        other_organization = Organization.objects.create(name="Other")
        other_dashboard = CrossProjectDashboard.objects.create(organization=other_organization, name="Theirs")
        CrossProjectDashboardTile.objects.create(
            dashboard=other_dashboard, organization=other_organization, project_id=self.team.pk, insight_id=1
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == []

    def test_pages_through_tiles_created_in_the_same_instant(self, _flag):
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
            created = {
                str(
                    CrossProjectDashboardTile.objects.create(
                        dashboard=self.dashboard, organization=self.organization, project_id=self.team.pk, insight_id=n
                    ).id
                )
                for n in range(3)
            }

        first = self.client.get(self._url("?limit=2")).json()
        second = self.client.get(self._url("?limit=2&offset=2")).json()

        paged = [tile["id"] for tile in first["results"] + second["results"]]
        assert first["count"] == 3
        assert sorted(paged) == sorted(created)

    @parameterized.expand(
        [
            ("everyone_denied", False),
            # Most-specific resolution lets the member's own denial beat the role's grant, while
            # the legacy resolver takes the highest of the two and would show the project.
            ("member_denied_role_allowed", True),
        ]
    )
    def test_a_project_the_reader_is_denied_hides_its_tiles(self, _flag, _name: str, member_denied: bool):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.uses_most_specific_access_resolution = True
        self.organization.save()
        denied_team = Team.objects.create(organization=self.organization, name="Denied project")
        if member_denied:
            role = Role.objects.create(name="Analysts", organization=self.organization)
            RoleMembership.objects.create(user=self.user, role=role)
            AccessControl.objects.create(
                team=denied_team, resource="project", resource_id=str(denied_team.id), role=role, access_level="admin"
            )
            AccessControl.objects.create(
                team=denied_team,
                resource="project",
                resource_id=str(denied_team.id),
                organization_member=OrganizationMembership.objects.get(organization=self.organization, user=self.user),
                access_level="none",
            )
        else:
            AccessControl.objects.create(
                team=denied_team, resource="project", resource_id=str(denied_team.id), access_level="none"
            )
        visible = CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard, organization=self.organization, project_id=self.team.pk, insight_id=1
        )
        CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard, organization=self.organization, project_id=denied_team.pk, insight_id=2
        )

        tiles = self.client.get(self._url()).json()["results"]
        dashboard = self.client.get(
            f"/api/organizations/{self.organization.id}/cross_project_dashboards/{self.dashboard.id}/"
        ).json()

        listed = self.client.get(f"/api/organizations/{self.organization.id}/cross_project_dashboards/").json()

        assert [tile["id"] for tile in tiles] == [str(visible.id)]
        assert [tile["id"] for tile in dashboard["tiles"]] == [str(visible.id)]
        assert (listed["results"][0]["tile_count"], listed["results"][0]["project_count"]) == (1, 1)

    @parameterized.expand([("patch",), ("delete",), ("add_tile",), ("patch_tile",), ("delete_tile",)])
    def test_a_member_denied_a_tile_project_cannot_change_the_dashboard(self, _flag, method: str):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        denied_team = Team.objects.create(organization=self.organization, name="Denied project")
        AccessControl.objects.create(
            team=denied_team, resource="project", resource_id=str(denied_team.id), access_level="none"
        )
        CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard, organization=self.organization, project_id=denied_team.pk, insight_id=2
        )
        url = f"/api/organizations/{self.organization.id}/cross_project_dashboards/{self.dashboard.id}/"

        visible = CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard, organization=self.organization, project_id=self.team.pk, insight_id=1
        )

        if method == "add_tile":
            body = {"project_id": self.team.pk, "insight_id": self._insight().pk}
            response = self.client.post(self._url(), body, format="json")
        elif method == "patch_tile":
            response = self.client.patch(self._url(f"{visible.id}/"), {"color": "red"}, format="json")
        elif method == "delete_tile":
            response = self.client.delete(self._url(f"{visible.id}/"))
        else:
            response = getattr(self.client, method)(url, {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        self.dashboard.refresh_from_db()
        assert (self.dashboard.name, self.dashboard.deleted) == ("Company overview", False)
        assert self.dashboard.tiles.filter(deleted=False).count() == 2
        visible.refresh_from_db()
        assert visible.color is None

    @parameterized.expand([("deleted",), ("moved_to_another_organization",)])
    def test_a_tile_whose_project_is_gone_hides_its_settings_and_never_blocks_the_dashboard(self, _flag, how: str):
        if how == "deleted":
            project_id = 987654321
        else:
            project_id = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Moved").pk
        gone = CrossProjectDashboardTile.objects.create(
            dashboard=self.dashboard,
            organization=self.organization,
            project_id=project_id,
            insight_id=1,
            color="red",
            filters_overrides={"properties": [{"type": "person", "key": "email", "value": "someone@example.com"}]},
        )
        dashboard_url = f"/api/organizations/{self.organization.id}/cross_project_dashboards/{self.dashboard.id}/"

        listed = self.client.get(self._url()).json()["results"]
        detail = self.client.get(dashboard_url).json()["tiles"]
        renamed = self.client.patch(dashboard_url, {"name": "Renamed"}, format="json")
        removed = self.client.delete(self._url(f"{gone.id}/"))

        assert [(tile["id"], tile["color"], tile["filters_overrides"]) for tile in listed + detail] == [
            (str(gone.id), None, {}),
            (str(gone.id), None, {}),
        ]
        assert renamed.status_code == status.HTTP_200_OK, renamed.json()
        assert removed.status_code == status.HTTP_204_NO_CONTENT

    def test_dashboard_patch_no_longer_writes_tiles(self, _flag):
        insight = self._insight()
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/cross_project_dashboards/{self.dashboard.id}/",
            {"tiles": [{"project_id": self.team.pk, "insight_id": insight.pk}]},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.dashboard.tiles.count() == 0

    def test_denies_everything_when_the_flag_is_off(self, flag):
        flag.return_value = False
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN
