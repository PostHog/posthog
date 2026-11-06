import json
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    NonAtomicAPIBaseTest,
    _create_event,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.http import StreamingHttpResponse

from parameterized import parameterized

from posthog.hogql.query import sync_execute

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight


class TestDashboardQuerySharingAccess(APIBaseTest):
    def test_flag_and_membership_validation(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Sharing test")
        url = f"/api/projects/{self.team.pk}/dashboards/{dashboard.pk}/stream_query_results/"
        params = {"tile_ids": "1", "client_query_id": str(uuid4()), "refresh": "blocking"}
        with patch("posthog.hogql.multi_query.posthoganalytics.feature_enabled", return_value=False):
            self.assertEqual(self.client.get(url, params).status_code, 403)
        with patch("posthog.hogql.multi_query.posthoganalytics.feature_enabled", return_value=True):
            self.assertEqual(self.client.get(url, {**params, "tile_ids": "bad"}).status_code, 400)
            self.assertEqual(self.client.get(url, params).status_code, 400)
            other = Dashboard.objects.create(team=self.team, name="Other dashboard")
            foreign_tile = DashboardTile.objects.create(dashboard=other, insight=Insight.objects.create(team=self.team))
            self.assertEqual(self.client.get(url, {**params, "tile_ids": str(foreign_tile.pk)}).status_code, 400)
            self.client.logout()
            self.assertIn(self.client.get(url, params).status_code, (401, 403))


class TestDashboardQuerySharingExecution(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    @parameterized.expand([("top_n", False), ("counts", True)])
    def test_shared_results_are_independently_cached(self, _name: str, counts: bool) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Sharing test")
        queries = [
            "SELECT event, count() AS n FROM events GROUP BY event ORDER BY n DESC, event LIMIT 1",
            "SELECT event, count() AS n FROM events GROUP BY event ORDER BY event LIMIT 2",
        ]
        expected: list[list[list[str | int]]] = [[["alpha", 2]], [["alpha", 2], ["beta", 1]]]
        if counts:
            queries = ["SELECT count() AS n FROM events", "SELECT count(uuid) AS n FROM events WHERE event = 'alpha'"]
            expected = [[[3]], [[2]]]
        tiles = [
            DashboardTile.objects.create(
                dashboard=dashboard,
                insight=Insight.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": query}),
            )
            for query in queries
        ]
        for event in ["alpha", "alpha", "beta"]:
            _create_event(team=self.team, event=event, distinct_id="synthetic-person")
        flush_persons_and_events()
        params = {
            "tile_ids": ",".join(str(tile.id) for tile in tiles),
            "debug": "true",
            "client_query_id": str(uuid4()),
            "refresh": "blocking",
        }
        with (
            patch(
                "posthog.hogql.multi_query.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "hogql-query-sharing",
            ),
            patch("products.dashboards.backend.query_sharing.MATCH_WINDOW_SECONDS", 30),
            patch("posthog.hogql.query.sync_execute", wraps=sync_execute) as execute,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/dashboards/{dashboard.pk}/stream_query_results/", params
            )
            self.assertEqual(response.status_code, 200)
            stream_response = cast(StreamingHttpResponse, response)
            events = [
                json.loads(chunk.removeprefix(b"data: ").strip())
                for chunk in cast(Iterator[bytes], stream_response.streaming_content)
            ]
            response.close()
            results = {event["tile"]["id"]: event["tile"] for event in events if event["type"] == "tile"}
            self.assertEqual(results[tiles[0].id]["insight"]["result"], expected[0], results)
            self.assertEqual(results[tiles[1].id]["insight"]["result"], expected[1], results)
            diagnostics = [event["debug"] for event in events if event["type"] == "tile"]
            shared = [entry for debug in diagnostics for entry in debug["executions"] if entry["outcome"] == "shared"]
            self.assertEqual(len(shared), 1)
            self.assertEqual(set(shared[0]["tile_ids"]), {tile.id for tile in tiles})
            self.assertEqual(shared[0]["rule"], "count_fusion" if counts else "same_aggregation_top_n")
            self.assertEqual(sum(debug["query_count"] for debug in diagnostics), 1)
            self.assertGreater(sum(debug["rows_read"] for debug in diagnostics), 0)
            self.assertGreater(sum(debug["duration_ms"] for debug in diagnostics), 0)
            prefix = "__batch_" if counts else "__sharing_"
            self.assertEqual(
                sum(prefix in str(call.args[0]) for call in execute.call_args_list),
                1,
                [str(call.args[0]) for call in execute.call_args_list],
            )
            for tile in tiles:
                cached = self.client.get(
                    f"/api/projects/{self.team.pk}/insights/{tile.insight_id}/",
                    {"refresh": "force_cache", "from_dashboard": str(dashboard.pk)},
                ).json()
                self.assertEqual(cached["result"], results[tile.id]["insight"]["result"])
                self.assertTrue(cached["is_cached"])
                self.assertNotIn("debug", cached)
            execute.reset_mock()
            response = self.client.get(
                f"/api/projects/{self.team.pk}/dashboards/{dashboard.pk}/stream_query_results/", params
            )
            stream_response = cast(StreamingHttpResponse, response)
            cached_events = [
                json.loads(chunk.removeprefix(b"data: ").strip())
                for chunk in cast(Iterator[bytes], stream_response.streaming_content)
            ]
            response.close()
            self.assertEqual(sum(event["type"] == "tile" for event in cached_events), 2)
            self.assertTrue(
                all(event["tile"]["insight"]["is_cached"] for event in cached_events if event["type"] == "tile")
            )
            execute.assert_not_called()
            for event in cached_events:
                if event["type"] == "tile":
                    self.assertEqual(event["debug"]["query_count"], 0)
                    self.assertEqual(event["debug"]["rows_read"], 0)
                    self.assertEqual(event["debug"]["executions"], [])
