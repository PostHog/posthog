import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.constants import MAX_CACHED_TILES_BATCH_SIZE
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.event_definitions.backend.models import PropertyDefinition


def _event_count_query(event: str) -> dict:
    return {
        "kind": "DataTableNode",
        "source": {"kind": "EventsQuery", "select": ["count()"], "event": event},
    }


class TestDashboardCachedTiles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.flag_patcher = patch("posthoganalytics.feature_enabled", side_effect=self._flag_enabled)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)
        self.flag_on_for_project: int | None = self.team.pk
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash", "filters": {"date_from": "-14d"}})

    def _flag_enabled(self, flag: str, distinct_id: str, **kwargs: Any) -> bool:
        groups = kwargs.get("groups") or {}
        return flag == "dashboard-v2" and groups.get("project") == str(self.flag_on_for_project)

    def _add_insight_tile(self, event: str) -> tuple[int, int]:
        insight_id, _ = self.dashboard_api.create_insight(
            {"name": event, "query": _event_count_query(event), "dashboards": [self.dashboard_id]}
        )
        tile = DashboardTile.objects.get(dashboard_id=self.dashboard_id, insight_id=insight_id)
        return insight_id, tile.id

    def _per_tile(self, insight_id: int, refresh: str) -> dict:
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight_id}/",
            {"from_dashboard": str(self.dashboard_id), "refresh": refresh},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def _cached_tiles(self, tile_ids: list[int], params: dict[str, str] | None = None) -> Any:
        return self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/cached_tiles/",
            {"tile_ids": ",".join(str(tile_id) for tile_id in tile_ids), **(params or {})},
        )

    def _statuses(self, tile_ids: list[int]) -> list[tuple[int, str]]:
        response = self._cached_tiles(tile_ids)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return [(tile["id"], tile["status"]) for tile in response.json()["results"]]

    def test_serves_what_the_per_tile_endpoint_cached_and_marks_the_rest(self) -> None:
        warm_insight_id, warm_tile_id = self._add_insight_tile("$pageview")
        _, cold_tile_id = self._add_insight_tile("$autocapture")
        self._per_tile(warm_insight_id, "blocking")
        per_tile = self._per_tile(warm_insight_id, "force_cache")

        response = self._cached_tiles([cold_tile_id, warm_tile_id, 999999])

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        cold, warm, unknown = response.json()["results"]
        self.assertEqual(cold, {"id": cold_tile_id, "status": "miss"})
        self.assertEqual(unknown, {"id": 999999, "status": "not_found"})
        self.assertEqual(warm["status"], "hit")
        self.assertEqual(warm["insight"]["result"], per_tile["result"])
        self.assertEqual(warm["insight"]["last_refresh"], per_tile["last_refresh"])
        self.assertNotIn("hogql", warm["insight"])

    def test_dashboard_filter_override_reads_its_own_cache_entry(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._per_tile(insight_id, "blocking")

        response = self._cached_tiles([tile_id], {"filters_override": '{"date_from": "-30d"}'})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["results"], [{"id": tile_id, "status": "miss"}])

    def test_a_user_who_cannot_view_the_insight_gets_no_result(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._per_tile(insight_id, "blocking")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="insight", resource_id=str(insight_id), access_level="none"
        )
        member = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        response = self._cached_tiles([tile_id])

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["results"], [{"id": tile_id, "status": "forbidden"}])
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}/").status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_a_user_who_cannot_view_the_dashboard_gets_nothing(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._per_tile(insight_id, "blocking")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="dashboard", resource_id=str(self.dashboard_id), access_level="none"
        )
        member = self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER)
        self.client.force_login(member)

        response = self._cached_tiles([tile_id])

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertNotIn("result", response.json())

    def test_a_property_restriction_keeps_results_cached_without_it_out(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._per_tile(insight_id, "blocking")
        self.assertEqual(self._statuses([tile_id]), [(tile_id, "hit")])

        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        secret = PropertyDefinition.objects.create(
            team=self.team, name="secret_prop", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=secret, access_level=PropertyAccessLevel.NONE.value
        )

        self.assertEqual(self._statuses([tile_id]), [(tile_id, "miss")])
        self._per_tile(insight_id, "blocking")
        self.assertEqual(self._statuses([tile_id]), [(tile_id, "hit")])

    def test_flag_off_for_the_project_returns_404(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._per_tile(insight_id, "blocking")
        self.flag_on_for_project = self.team.pk + 1

        response = self._cached_tiles([tile_id])

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)
        self.assertEqual(self._per_tile(insight_id, "force_cache")["is_cached"], True)

    @parameterized.expand(
        [
            ("refresh_is_rejected", {"refresh": "blocking"}),
            ("tile_ids_are_required", {"tile_ids": ""}),
            ("too_many_tile_ids", {"tile_ids": ",".join(str(i) for i in range(1, MAX_CACHED_TILES_BATCH_SIZE + 2))}),
        ]
    )
    def test_rejects_invalid_requests(self, _name: str, params: dict[str, str]) -> None:
        _, tile_id = self._add_insight_tile("$pageview")

        response = self._cached_tiles([tile_id], params)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)

    def test_rejects_refresh_in_a_get_body(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")

        with patch("posthog.caching.calculate_results.calculate_for_query_based_insight") as calculate:
            response = self.client.generic(
                "GET",
                f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/cached_tiles/?tile_ids={tile_id}",
                json.dumps({"refresh": "force_blocking"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        calculate.assert_not_called()

    def test_reads_the_entry_the_per_tile_endpoint_wrote_for_stale_variable_ids(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.pk}/insight_variables/",
            {"name": "Test 1", "type": "String", "default_value": "a"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        code_name = response.json()["code_name"]
        stale_id = "00000000-0000-0000-0000-000000000000"
        insight_id, _ = self.dashboard_api.create_insight(
            {
                "name": "sql",
                "query": {
                    "kind": "DataVisualizationNode",
                    "source": {
                        "kind": "HogQLQuery",
                        "query": f"select {{variables.{code_name}}}",
                        "variables": {stale_id: {"code_name": code_name, "variableId": stale_id}},
                    },
                },
                "dashboards": [self.dashboard_id],
            }
        )
        tile_id = DashboardTile.objects.get(dashboard_id=self.dashboard_id, insight_id=insight_id).id
        self._per_tile(insight_id, "blocking")

        self.assertEqual(self._statuses([tile_id]), [(tile_id, "hit")])

    def test_postgres_queries_do_not_grow_with_tile_count(self) -> None:
        tiles = [self._add_insight_tile(event) for event in ("$pageview", "$autocapture", "$identify", "$pageleave")]
        for insight_id, _ in tiles:
            self._per_tile(insight_id, "blocking")
        tile_ids = [tile_id for _, tile_id in tiles]
        self._statuses(tile_ids)

        with CaptureQueriesContext(connection) as one_tile:
            self.assertEqual(self._statuses(tile_ids[:1]), [(tile_ids[0], "hit")])
        with CaptureQueriesContext(connection) as four_tiles:
            self.assertEqual(self._statuses(tile_ids), [(tile_id, "hit") for tile_id in tile_ids])

        self.assertEqual(len(four_tiles.captured_queries), len(one_tile.captured_queries))
