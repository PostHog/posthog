from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models.quick_filter import QuickFilter

from products.dashboards.backend.models.dashboard import Dashboard


@override_settings(IN_UNIT_TESTING=True)
class TestQuickFilters(APIBaseTest):
    def _create_quick_filter(
        self,
        name: str = "Environment",
        property_name: str = "$environment",
        contexts: list[str] | None = None,
    ) -> tuple[dict, QuickFilter]:
        response = self.client.post(
            f"/api/environments/{self.team.id}/quick_filters/",
            {
                "name": name,
                "property_name": property_name,
                "type": "manual-options",
                "options": [
                    {"id": "prod", "value": "production", "label": "Production", "operator": "exact"},
                    {"id": "dev", "value": "development", "label": "Development", "operator": "exact"},
                ],
                "contexts": contexts or ["dashboards"],
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        return data, QuickFilter.objects.get(id=data["id"])

    def test_create_quick_filter(self):
        data, _ = self._create_quick_filter("Browser", "$browser")

        assert data["name"] == "Browser"
        assert data["property_name"] == "$browser"
        assert len(data["options"]) == 2
        assert data["contexts"] == ["dashboards"]

    def test_list_quick_filters(self):
        self._create_quick_filter("Filter 1", "$prop1")
        self._create_quick_filter("Filter 2", "$prop2")

        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

    def test_list_quick_filters_by_context(self):
        self._create_quick_filter("Dashboard Filter", "$dashboard_prop")
        self._create_quick_filter("Logs Filter", "$logs_prop", contexts=["logs-filters"])

        # Unfiltered returns both
        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 2

        # Filtered by context returns only the matching one
        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/?context=dashboards")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Dashboard Filter"

    def test_delete_quick_filter(self):
        _, quick_filter = self._create_quick_filter()

        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not QuickFilter.objects.filter(id=quick_filter.id).exists()

    def test_delete_quick_filter_removes_from_dashboards(self):
        _, qf1 = self._create_quick_filter("Filter 1", "$prop1")
        _, qf2 = self._create_quick_filter("Filter 2", "$prop2")

        dashboard_1 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 1",
            quick_filter_ids=[str(qf1.id), str(qf2.id)],
        )
        dashboard_2 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 2",
            quick_filter_ids=[str(qf1.id)],
        )
        dashboard_3 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 3",
            quick_filter_ids=[str(qf2.id)],
        )
        dashboard_null = Dashboard.objects.create(
            team=self.team,
            name="Dashboard null",
            quick_filter_ids=None,
        )
        dashboard_empty = Dashboard.objects.create(
            team=self.team,
            name="Dashboard empty",
            quick_filter_ids=[],
        )

        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{qf1.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        dashboard_1.refresh_from_db()
        dashboard_2.refresh_from_db()
        dashboard_3.refresh_from_db()
        dashboard_null.refresh_from_db()
        dashboard_empty.refresh_from_db()

        assert dashboard_1.quick_filter_ids == [str(qf2.id)]
        assert dashboard_2.quick_filter_ids == []
        assert dashboard_3.quick_filter_ids == [str(qf2.id)]
        assert dashboard_null.quick_filter_ids is None
        assert dashboard_empty.quick_filter_ids == []

    def test_dashboard_rejects_cross_team_quick_filter_ids(self):
        _, quick_filter = self._create_quick_filter()

        other_team = self.organization.teams.create(name="Other Team")
        dashboard = Dashboard.objects.create(team=other_team, name="Other Dashboard")

        response = self.client.patch(
            f"/api/environments/{other_team.id}/dashboards/{dashboard.id}/",
            {"quick_filter_ids": [str(quick_filter.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
