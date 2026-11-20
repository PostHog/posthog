import re
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog import redis
from posthog.api.test.dashboards import DashboardAPI
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.dashboards.backend.constants import MAX_CACHED_TILES_BATCH_SIZE
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.event_definitions.backend.models import PropertyDefinition


class _CountingClient:
    def __init__(self, client: Any, counted: frozenset[str]) -> None:
        self.client = client
        self.counted = counted
        self.round_trips = 0

    def __getattr__(self, name: str) -> Any:
        if name in self.counted:
            self.round_trips += 1
        return getattr(self.client, name)


@frozen
class _RedisRoundTrips:
    cache_reads: _CountingClient
    read_history_writes: _CountingClient


@contextmanager
def _count_redis_round_trips() -> Iterator[_RedisRoundTrips]:
    counts = _RedisRoundTrips(
        cache_reads=_CountingClient(redis.get_client(), frozenset({"get", "mget", "mget_nonatomic"})),
        read_history_writes=_CountingClient(redis.get_client(), frozenset({"pipeline"})),
    )
    with (
        patch("posthog.query_cache.storage.query_cache_read_client", return_value=counts.cache_reads),
        patch("posthog.query_cache.read_history.redis.get_client", return_value=counts.read_history_writes),
    ):
        yield counts


_RUN_ID_KEYS = frozenset({"id", "dashboard_id", "short_id", "uuid", "distinct_id"})


def _without_run_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<run id>" if key in _RUN_ID_KEYS else _without_run_ids(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_run_ids(item) for item in value]
    if isinstance(value, str):
        # A cache key hashes the team's ID, which differs on every run.
        return re.sub(r"^cache_\d+_[0-9a-f]+$", "<cache key>", value)
    return value


def _sql_count_query(event: str) -> dict:
    return {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": f"select count() from events where event = '{event}'"},
    }


def _trends_query(event: str) -> dict:
    return {
        "kind": "InsightVizNode",
        "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": event}]},
    }


def _event_count_query(event: str) -> dict:
    return {
        "kind": "DataTableNode",
        "source": {"kind": "EventsQuery", "select": ["count()"], "event": event},
    }


@pytest.mark.usefixtures("unittest_snapshot")
class TestDashboardCachedTiles(APIBaseTest):
    snapshot: Any

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

    def _add_insight_tile(self, event: str, query: dict | None = None) -> tuple[int, int]:
        insight_id, _ = self.dashboard_api.create_insight(
            {"name": event, "query": query or _event_count_query(event), "dashboards": [self.dashboard_id]}
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

    def _statuses(self, tile_ids: list[int], params: dict[str, str] | None = None) -> list[tuple[int, str]]:
        response = self._cached_tiles(tile_ids, params)
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
        self.assertEqual(warm["insight"]["query_scan"], per_tile["query_scan"])
        self.assertNotIn("hogql", warm["insight"])

    @parameterized.expand([("blocking",), ("force_cache",)])
    def test_per_tile_insight_endpoint_without_dashboard_v2_is_unchanged(self, _name: str) -> None:
        self.flag_on_for_project = None
        with time_machine.travel("2026-06-01T12:00:00Z", tick=False):
            insight_id, _ = self._add_insight_tile("$pageview")
            self._per_tile(insight_id, "blocking")

            with _count_redis_round_trips() as redis_calls:
                payload = self._per_tile(insight_id, _name)

        self.assertEqual(
            (redis_calls.cache_reads.round_trips, redis_calls.read_history_writes.round_trips),
            (1, 1),
        )
        assert _without_run_ids(payload) == self.snapshot

    def test_frames_format_frames_trends_and_returns_other_results_as_they_are(self) -> None:
        trends_insight_id, trends_tile_id = self._add_insight_tile(
            "$pageview",
            {
                "kind": "InsightVizNode",
                "source": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )
        table_insight_id, table_tile_id = self._add_insight_tile("$autocapture")
        self._per_tile(trends_insight_id, "blocking")
        self._per_tile(table_insight_id, "blocking")
        table_result = self._per_tile(table_insight_id, "force_cache")["result"]

        response = self._cached_tiles([trends_tile_id, table_tile_id], {"format": "frames"})

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        trends, table = response.json()["results"]
        self.assertEqual((trends["status"], trends["format"]), ("hit", "frames"))
        self.assertNotIn("result", trends["insight"])
        [frame] = trends["frames"]
        self.assertEqual(frame["name"], "$pageview")
        self.assertEqual(
            [(field["name"], field["type"]) for field in frame["fields"]], [("time", "time"), ("value", "number")]
        )
        self.assertEqual(len(frame["fields"][0]["values"]), 15)
        self.assertEqual(frame["meta"]["interval"], "day")
        self.assertEqual(frame["meta"]["date_from"][:10], trends["insight"]["resolved_date_range"]["date_from"][:10])
        self.assertEqual((table["status"], table["format"]), ("hit", "result"))
        self.assertNotIn("frames", table)
        self.assertEqual(table["insight"]["result"], table_result)

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

    @parameterized.expand(
        [
            # Raw SQL tiles, because their cache keys look up warehouse names in Postgres.
            ("result", _sql_count_query, {}),
            # Trends tiles, because frames are built from their parsed results.
            ("frames", _trends_query, {"format": "frames"}),
        ]
    )
    def test_postgres_queries_and_redis_round_trips_do_not_grow_with_tile_count(
        self, _name: str, tile_query: Callable[[str], dict], params: dict[str, str]
    ) -> None:
        tiles = [
            self._add_insight_tile(event, tile_query(event))
            for event in ("$pageview", "$autocapture", "$identify", "$pageleave")
        ]
        for insight_id, _ in tiles:
            self._per_tile(insight_id, "blocking")
        tile_ids = [tile_id for _, tile_id in tiles]
        self._statuses(tile_ids, params)

        with CaptureQueriesContext(connection) as one_tile, _count_redis_round_trips() as one_tile_redis:
            self.assertEqual(self._statuses(tile_ids[:1], params), [(tile_ids[0], "hit")])
        with CaptureQueriesContext(connection) as four_tiles, _count_redis_round_trips() as four_tile_redis:
            self.assertEqual(self._statuses(tile_ids, params), [(tile_id, "hit") for tile_id in tile_ids])

        self.assertEqual(len(four_tiles.captured_queries), len(one_tile.captured_queries))
        self.assertEqual(
            [
                (redis.cache_reads.round_trips, redis.read_history_writes.round_trips)
                for redis in (one_tile_redis, four_tile_redis)
            ],
            [(1, 1), (1, 1)],
        )

    @parameterized.expand(
        [
            ("flag_on_with_param_omits_results", True, {"omit_tile_results": "true"}, False),
            ("flag_on_without_param_keeps_results", True, {}, True),
            ("flag_off_ignores_param", False, {"omit_tile_results": "true"}, True),
        ]
    )
    def test_dashboard_get_omits_tile_results_only_when_asked_under_the_flag(
        self, _name: str, flag_on: bool, params: dict[str, str], expect_result: bool
    ) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        cached = self._per_tile(insight_id, "blocking")
        if not flag_on:
            self.flag_on_for_project = self.team.pk + 1

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/",
            {"refresh": "force_cache", "filters_override": '{"date_from": "-14d"}', **params},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        (tile,) = response.json()["tiles"]
        self.assertEqual(tile["id"], tile_id)
        self.assertEqual(tile["insight"]["name"], "$pageview")
        self.assertEqual(tile["insight"]["query"], cached["query"])
        self.assertEqual(tile["insight"]["result"] is not None, expect_result)
        self.assertEqual(tile["insight"]["is_cached"], expect_result)
        self.assertEqual(tile["insight"]["last_refresh"] is not None, expect_result)
        if flag_on:
            self.assertEqual(self._statuses([tile_id]), [(tile_id, "hit")])

    def test_dashboard_get_without_results_still_masks_restricted_insights(self) -> None:
        insight_id, _ = self._add_insight_tile("$pageview")
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

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/",
            {"refresh": "force_cache", "omit_tile_results": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        (tile,) = response.json()["tiles"]
        self.assertEqual(
            tile["insight"], {"id": insight_id, "short_id": tile["insight"]["short_id"], "user_access_level": "none"}
        )
