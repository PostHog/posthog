from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status

from posthog.models import Dashboard
from posthog.models.quick_filter import QuickFilter, QuickFilterContext


@override_settings(IN_UNIT_TESTING=True)
class TestQuickFilters(APIBaseTest):
    def _create_quick_filter(self, name: str = "Environment", property_name: str = "$environment") -> QuickFilter:
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
                "contexts": ["dashboards"],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return QuickFilter.objects.get(id=response.json()["id"])

    def test_create_quick_filter(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/quick_filters/",
            {
                "name": "Browser",
                "property_name": "$browser",
                "type": "manual-options",
                "options": [
                    {"id": "chrome", "value": "Chrome", "label": "Chrome", "operator": "exact"},
                    {"id": "firefox", "value": "Firefox", "label": "Firefox", "operator": "exact"},
                ],
                "contexts": ["dashboards"],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Browser")
        self.assertEqual(response.json()["property_name"], "$browser")
        self.assertEqual(len(response.json()["options"]), 2)
        self.assertEqual(response.json()["contexts"], ["dashboards"])

    def test_list_quick_filters(self):
        self._create_quick_filter("Filter 1", "$prop1")
        self._create_quick_filter("Filter 2", "$prop2")

        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_quick_filters_by_context(self):
        self._create_quick_filter("Dashboard Filter", "$dashboard_prop")

        # Create a filter with different context
        qf = QuickFilter.objects.create(
            team=self.team,
            name="Other Filter",
            property_name="$other_prop",
            type="manual-options",
            options=[{"id": "1", "value": "val", "label": "Val", "operator": "exact"}],
        )
        QuickFilterContext.objects.create(team=self.team, quick_filter=qf, context="logs-filters")

        response = self.client.get(f"/api/environments/{self.team.id}/quick_filters/?context=dashboards")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "Dashboard Filter")

    def test_delete_quick_filter(self):
        quick_filter = self._create_quick_filter()

        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(QuickFilter.objects.filter(id=quick_filter.id).exists())

    def test_delete_quick_filter_removes_from_dashboards(self):
        quick_filter_1 = self._create_quick_filter("Filter 1", "$prop1")
        quick_filter_2 = self._create_quick_filter("Filter 2", "$prop2")

        # Create dashboards with quick_filter_ids
        dashboard_1 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 1",
            quick_filter_ids=[str(quick_filter_1.id), str(quick_filter_2.id)],
        )
        dashboard_2 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 2",
            quick_filter_ids=[str(quick_filter_1.id)],
        )
        dashboard_3 = Dashboard.objects.create(
            team=self.team,
            name="Dashboard 3",
            quick_filter_ids=[str(quick_filter_2.id)],
        )

        # Delete quick_filter_1
        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter_1.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Refresh dashboards from DB
        dashboard_1.refresh_from_db()
        dashboard_2.refresh_from_db()
        dashboard_3.refresh_from_db()

        # quick_filter_1 should be removed from dashboard_1 and dashboard_2
        self.assertEqual(dashboard_1.quick_filter_ids, [str(quick_filter_2.id)])
        self.assertEqual(dashboard_2.quick_filter_ids, [])
        # dashboard_3 should be unchanged
        self.assertEqual(dashboard_3.quick_filter_ids, [str(quick_filter_2.id)])

    def test_delete_quick_filter_handles_null_quick_filter_ids(self):
        quick_filter = self._create_quick_filter()

        # Create dashboard with null quick_filter_ids
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with null",
            quick_filter_ids=None,
        )

        # Delete should not fail
        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        dashboard.refresh_from_db()
        self.assertIsNone(dashboard.quick_filter_ids)

    def test_delete_quick_filter_handles_empty_quick_filter_ids(self):
        quick_filter = self._create_quick_filter()

        # Create dashboard with empty quick_filter_ids
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with empty",
            quick_filter_ids=[],
        )

        # Delete should not fail
        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.quick_filter_ids, [])

    def test_delete_quick_filter_only_affects_same_team(self):
        quick_filter = self._create_quick_filter()

        # Create another team and dashboard
        other_team = self.organization.teams.create(name="Other Team")
        other_dashboard = Dashboard.objects.create(
            team=other_team,
            name="Other Dashboard",
            quick_filter_ids=[str(quick_filter.id)],  # Same ID, but different team
        )

        # Delete quick_filter
        response = self.client.delete(f"/api/environments/{self.team.id}/quick_filters/{quick_filter.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Other team's dashboard should be unchanged
        other_dashboard.refresh_from_db()
        self.assertEqual(other_dashboard.quick_filter_ids, [str(quick_filter.id)])
