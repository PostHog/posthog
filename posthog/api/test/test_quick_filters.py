from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models import Dashboard
from posthog.models.quick_filter import QuickFilter


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
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        return data, QuickFilter.objects.get(id=data["id"])

    def test_create_quick_filter(self):
        data, _ = self._create_quick_filter("Browser", "$browser")

        self.assertEqual(data["name"], "Browser")
        self.assertEqual(data["property_name"], "$browser")
        self.assertEqual(len(data["options"]), 2)
        self.assertEqual(data["contexts"], ["dashboards"])

    def test_list_quick_filters(self):
        self._create_quick_filter("Filter 1", "$prop1")
        self._create_quick_filter("Filter 2", "$prop2")

        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_quick_filters_by_context(self):
        self._create_quick_filter("Dashboard Filter", "$dashboard_prop")
        self._create_quick_filter("Logs Filter", "$logs_prop", contexts=["logs-filters"])

        # Unfiltered returns both
        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

        # Filtered by context returns only the matching one
        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/?context=dashboards")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Dashboard Filter")

    def test_delete_quick_filter(self):
        _, quick_filter = self._create_quick_filter()

        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(QuickFilter.objects.filter(id=quick_filter.id).exists())

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
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        dashboard_1.refresh_from_db()
        dashboard_2.refresh_from_db()
        dashboard_3.refresh_from_db()
        dashboard_null.refresh_from_db()
        dashboard_empty.refresh_from_db()

        self.assertEqual(dashboard_1.quick_filter_ids, [str(qf2.id)])
        self.assertEqual(dashboard_2.quick_filter_ids, [])
        self.assertEqual(dashboard_3.quick_filter_ids, [str(qf2.id)])
        self.assertIsNone(dashboard_null.quick_filter_ids)
        self.assertEqual(dashboard_empty.quick_filter_ids, [])

    def test_dashboard_rejects_cross_team_quick_filter_ids(self):
        _, quick_filter = self._create_quick_filter()

        other_team = self.organization.teams.create(name="Other Team")
        dashboard = Dashboard.objects.create(team=other_team, name="Other Dashboard")

        response = self.client.patch(
            f"/api/environments/{other_team.id}/dashboards/{dashboard.id}/",
            {"quick_filter_ids": [str(quick_filter.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
