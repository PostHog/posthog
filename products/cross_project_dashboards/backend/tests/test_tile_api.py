from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import Organization

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
