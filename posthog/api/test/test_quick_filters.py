from typing import Any

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.quick_filters import QuickFilterSerializer
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

    def test_list_quick_filters_pages_do_not_overlap_when_created_at_ties(self):
        for index in range(5):
            self._create_quick_filter(f"Filter {index}", f"$prop{index}")
        QuickFilter.objects.filter(team=self.team).update(created_at="2026-01-01T00:00:00Z")
        expected_order = [
            str(filter_id)
            for filter_id in QuickFilter.objects.filter(team=self.team).order_by("-id").values_list("id", flat=True)
        ]

        first_page = self.client.get(f"/api/environments/{self.team.id}/quick_filters/?limit=3")
        second_page = self.client.get(f"/api/environments/{self.team.id}/quick_filters/?limit=3&offset=3")

        self.assertEqual(first_page.status_code, status.HTTP_200_OK)
        self.assertEqual(second_page.status_code, status.HTTP_200_OK)
        paged_ids = [row["id"] for row in first_page.json()["results"]]
        paged_ids += [row["id"] for row in second_page.json()["results"]]
        self.assertEqual(paged_ids, expected_order)

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


MANUAL_OPTION = {"id": "prod", "value": "production", "label": "Production", "operator": "exact"}


class TestQuickFilterSerializerOptions(SimpleTestCase):
    @parameterized.expand(
        [
            ("auto_discovery_without_options", {"type": "auto-discovery"}, None, True, []),
            (
                "auto_discovery_drops_sent_options",
                {"type": "auto-discovery", "options": [MANUAL_OPTION]},
                None,
                True,
                [],
            ),
            ("manual_without_options", {"type": "manual-options"}, None, False, None),
            ("manual_with_empty_options", {"type": "manual-options", "options": []}, None, False, None),
            (
                "manual_with_options",
                {"type": "manual-options", "options": [MANUAL_OPTION]},
                None,
                True,
                [MANUAL_OPTION],
            ),
            ("switch_manual_to_auto", {"type": "auto-discovery"}, "manual-options", True, []),
            ("switch_auto_to_manual_without_options", {"type": "manual-options"}, "auto-discovery", False, None),
            ("rename_auto_discovery", {"name": "Renamed"}, "auto-discovery", True, []),
        ]
    )
    def test_options_depend_on_type(
        self,
        _name: str,
        data: dict[str, Any],
        instance_type: str | None,
        expected_valid: bool,
        expected_options: list[dict[str, Any]] | None,
    ) -> None:
        if instance_type is None:
            serializer = QuickFilterSerializer(data={"name": "Environment", "property_name": "$environment", **data})
        else:
            instance_options = [] if instance_type == "auto-discovery" else [MANUAL_OPTION]
            instance = QuickFilter(
                name="Environment", property_name="$environment", type=instance_type, options=instance_options
            )
            serializer = QuickFilterSerializer(instance, data=data, partial=True)

        self.assertEqual(serializer.is_valid(), expected_valid, serializer.errors)
        if expected_valid:
            self.assertEqual(serializer.validated_data.get("options"), expected_options)
        else:
            self.assertIn("options", serializer.errors)
