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
from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.query import sync_execute

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
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
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="query only",
                user=self.user,
                secure_value=hash_key_value(token),
                scopes=["query:read"],
                scoped_teams=[],
                scoped_organizations=[],
            )
            self.assertEqual(self.client.get(url, params, HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 403)
            self.client.logout()
            self.assertIn(self.client.get(url, params).status_code, (401, 403))

    def test_masks_insights_restricted_in_a_sibling_environment(self) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.team.project)
        dashboard = Dashboard.objects.create(team=sibling, name="Sharing test")
        insight = Insight.objects.create(
            team=sibling, name="Revenue by account", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(team=sibling, resource="insight", resource_id=str(insight.id), access_level="none")
        self.client.force_login(self._create_user("member@example.com", level=OrganizationMembership.Level.MEMBER))

        with patch("posthog.hogql.multi_query.posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/dashboards/{dashboard.pk}/stream_query_results/",
                {"tile_ids": str(tile.pk), "client_query_id": str(uuid4()), "refresh": "blocking"},
            )
            self.assertEqual(response.status_code, 200)
            body = b"".join(cast(Iterator[bytes], cast(StreamingHttpResponse, response).streaming_content))
            response.close()

        tiles = [json.loads(chunk) for chunk in body.decode().split("data: ") if '"type":"tile"' in chunk]
        self.assertEqual(tiles, [{"type": "tile", "tile": {"id": tile.pk, "error": {"type": "access_denied"}}}])
        self.assertNotIn("Revenue by account", body.decode())


class TestDashboardQuerySharingExecution(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    def test_tiles_share_one_native_alert_lookup(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Sharing test")
        tiles = [
            DashboardTile.objects.create(
                dashboard=dashboard,
                insight=Insight.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": f"SELECT {n}"}),
            )
            for n in (1, 2)
        ]
        with (
            patch(
                "posthog.hogql.multi_query.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == "hogql-query-sharing",
            ),
            # One worker serializes the tiles in turn, so the second tile reads what the first one loaded.
            patch("products.dashboards.backend.query_sharing_stream.WORKERS_PER_STREAM", 1),
            patch(
                "products.product_analytics.backend.presentation.insight.native_insight_alerts",
                return_value={},
            ) as lookup,
        ):
            response = self.client.get(
                f"/api/projects/{self.team.pk}/dashboards/{dashboard.pk}/stream_query_results/",
                {
                    "tile_ids": ",".join(str(tile.id) for tile in tiles),
                    "client_query_id": str(uuid4()),
                    "refresh": "blocking",
                },
            )
            self.assertEqual(response.status_code, 200)
            events = [
                json.loads(chunk.removeprefix(b"data: ").strip())
                for chunk in cast(Iterator[bytes], cast(StreamingHttpResponse, response).streaming_content)
            ]
            response.close()

        self.assertEqual(sum(event["type"] == "tile" for event in events), 2)
        self.assertEqual(lookup.call_count, 1)

    @parameterized.expand([("top_n", False, False), ("counts", True, False), ("daily_counts", True, True)])
    def test_shared_results_are_independently_cached(self, _name: str, counts: bool, daily: bool) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Sharing test")
        queries = [
            "SELECT event, count() AS n FROM events GROUP BY event ORDER BY n DESC, event LIMIT 1",
            "SELECT event, count() AS n FROM events GROUP BY event ORDER BY event LIMIT 2",
        ]
        expected: list[list[list[str | int]]] = [[["alpha", 2]], [["alpha", 2], ["beta", 1]]]
        if counts:
            queries = ["SELECT count() AS n FROM events", "SELECT count(uuid) AS n FROM events WHERE event = 'alpha'"]
            expected = [[[3]], [[2]]]
        if daily:
            # The runner's paginator adds a LIMIT to these, unlike the scalar counts above.
            daily_sql = (
                "SELECT toDate(timestamp) AS day, count() AS n FROM events{} GROUP BY toDate(timestamp) ORDER BY day"
            )
            queries = [daily_sql.format(""), daily_sql.format(" WHERE event = 'alpha'")]
            today = timezone.now().date().isoformat()
            expected = [[[today, 3]], [[today, 2]]]
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
