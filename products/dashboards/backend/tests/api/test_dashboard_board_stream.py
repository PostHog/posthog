import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import time_machine
from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.http import StreamingHttpResponse
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.presentation.views import dashboard as dashboard_views


def _event_count_query(event: str) -> dict:
    return {
        "kind": "DataTableNode",
        "source": {"kind": "EventsQuery", "select": ["count()"], "event": event},
    }


def _events(chunks: Iterator[bytes]) -> Iterator[dict[str, Any]]:
    for chunk in chunks:
        for frame in chunk.split(b"\n\n"):
            if frame.startswith(b"data: "):
                yield json.loads(frame.removeprefix(b"data: "))


class TestDashboardBoardStream(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.flag_patcher = patch("posthoganalytics.feature_enabled", side_effect=self._flag_enabled)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)
        self.dashboard_v2 = True
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "dash", "filters": {"date_from": "-14d"}})

    def _flag_enabled(self, flag: str, distinct_id: str, **kwargs: Any) -> bool:
        return flag in ("dashboard-v2", "dashboard-v2-users") and self.dashboard_v2

    def _add_insight_tile(self, event: str) -> tuple[int, int]:
        insight_id, _ = self.dashboard_api.create_insight(
            {"name": event, "query": _event_count_query(event), "dashboards": [self.dashboard_id]}
        )
        tile = DashboardTile.objects.get(dashboard_id=self.dashboard_id, insight_id=insight_id)
        return insight_id, tile.id

    def _warm(self, insight_id: int) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{insight_id}/",
            {"from_dashboard": str(self.dashboard_id), "refresh": "blocking"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def _open(self, tile_ids: list[int], refresh: str = "blocking") -> StreamingHttpResponse:
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/stream_query_results/",
            {
                "tile_ids": ",".join(str(tile_id) for tile_id in tile_ids),
                "client_query_id": str(uuid4()),
                "refresh": refresh,
                "cached_first": "true",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, getattr(response, "content", b""))
        return cast(StreamingHttpResponse, response)

    def _stream(self, tile_ids: list[int], refresh: str = "blocking") -> list[dict[str, Any]]:
        response = self._open(tile_ids, refresh)
        try:
            return list(_events(cast(Iterator[bytes], response.streaming_content)))
        finally:
            response.close()

    @parameterized.expand(
        [
            ("blocking_computes_stale_and_missing_only", "blocking", ["missing", "stale"]),
            ("force_recomputes_every_tile", "force_blocking", ["missing", "stale", "fresh"]),
        ]
    )
    def test_sends_cached_tiles_first_then_computes_in_request_order(
        self, _name: str, refresh: str, expected_pending: list[str]
    ) -> None:
        fresh_insight, fresh_tile = self._add_insight_tile("$pageview")
        stale_insight, stale_tile = self._add_insight_tile("$autocapture")
        _, missing_tile = self._add_insight_tile("$pageleave")
        with time_machine.travel(timezone.now() - timedelta(days=2), tick=False):
            self._warm(stale_insight)
        self._warm(fresh_insight)
        names = {fresh_tile: "fresh", stale_tile: "stale", missing_tile: "missing"}

        events = self._stream([missing_tile, stale_tile, fresh_tile], refresh)

        cached, *computed, done = events
        self.assertEqual(cached["type"], "cached")
        self.assertEqual(
            [(names[tile["id"]], tile["status"], tile.get("stale")) for tile in cached["tiles"]],
            [("missing", "miss", None), ("stale", "hit", True), ("fresh", "hit", False)],
        )
        self.assertIsNotNone(cached["tiles"][1]["insight"]["result"])
        self.assertEqual([names[tile_id] for tile_id in cached["pending"]], expected_pending)
        self.assertEqual([event["type"] for event in computed], ["tile"] * len(expected_pending))
        self.assertEqual(sorted(names[event["tile"]["id"]] for event in computed), sorted(expected_pending))
        for event in computed:
            self.assertFalse(event["tile"]["insight"]["query_status"] or {}, event)
            self.assertIsNotNone(event["tile"]["insight"]["result"])
        computed_queries = {event["tile"]["id"]: event["tile"]["insight"]["query"] for event in computed}
        cached_queries = {tile["id"]: tile["insight"]["query"] for tile in cached["tiles"] if tile["status"] == "hit"}
        for tile_id, query in cached_queries.items():
            if tile_id in computed_queries:
                self.assertEqual(query, computed_queries[tile_id])
        self.assertEqual(done, {"type": "complete"})

    def test_a_tile_the_user_cannot_view_gets_no_result(self) -> None:
        insight_id, tile_id = self._add_insight_tile("$pageview")
        self._warm(insight_id)
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="insight", resource_id=str(insight_id), access_level="none"
        )
        self.client.force_login(self._create_user("member@posthog.com", level=OrganizationMembership.Level.MEMBER))

        events = self._stream([tile_id], "force_blocking")

        self.assertEqual(
            events,
            [
                {"type": "cached", "tiles": [{"id": tile_id, "status": "forbidden"}], "pending": []},
                {"type": "complete"},
            ],
        )

    def test_flag_off_keeps_the_endpoint_closed(self) -> None:
        _, tile_id = self._add_insight_tile("$pageview")
        self.dashboard_v2 = False

        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/stream_query_results/",
            {"tile_ids": str(tile_id), "client_query_id": str(uuid4()), "refresh": "blocking", "cached_first": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_closing_the_stream_stops_tiles_that_have_not_started(self) -> None:
        tile_ids = [self._add_insight_tile(event)[1] for event in ("$pageview", "$autocapture", "$pageleave")]
        started: list[int] = []
        second_started = threading.Event()
        release = threading.Event()
        second_finished = threading.Event()
        serialize = dashboard_views.serialize_tile_with_context

        def serialize_blocking_on_second(tile: DashboardTile, order: int, context: dict) -> tuple[int, dict]:
            started.append(tile.id)
            if tile.id != tile_ids[1]:
                return serialize(tile, order, context)
            second_started.set()
            try:
                release.wait(timeout=10)
                return serialize(tile, order, context)
            finally:
                second_finished.set()

        with (
            patch("products.dashboards.backend.query_sharing_stream.WORKERS_PER_STREAM", 1),
            patch.object(dashboard_views, "serialize_tile_with_context", side_effect=serialize_blocking_on_second),
        ):
            response = self._open(tile_ids)
            events = _events(cast(Iterator[bytes], response.streaming_content))
            received = [next(events)["type"], next(events)["type"]]
            self.assertTrue(second_started.wait(timeout=10))
            response.close()
            release.set()
            self.assertTrue(second_finished.wait(timeout=10))

        self.assertEqual(received, ["cached", "tile"])
        self.assertEqual(started, tile_ids[:2])

    def test_a_full_organization_limiter_makes_the_tile_wait_instead_of_failing(self) -> None:
        _, tile_id = self._add_insight_tile("$pageview")
        attempts: list[int] = []

        @contextmanager
        def full_then_free(*args: Any, **kwargs: Any) -> Iterator[None]:
            attempts.append(1)
            if len(attempts) == 1:
                raise ConcurrencyLimitExceeded("Exceeded maximum concurrency limit")
            yield

        with (
            patch("posthog.hogql_queries.query_runner.app_org_concurrency_slot", side_effect=full_then_free),
            patch("products.dashboards.backend.query_sharing_stream.CAPACITY_RETRY_DELAY_SECONDS", 0.01),
        ):
            events = self._stream([tile_id])

        tile_events = [event for event in events if event["type"] == "tile"]
        self.assertEqual(len(tile_events), 1)
        self.assertFalse(tile_events[0]["tile"]["insight"]["query_status"] or {}, tile_events[0])
        self.assertIsNotNone(tile_events[0]["tile"]["insight"]["result"])
        self.assertEqual(len(attempts), 2)

    def test_capacity_waiting_shares_one_budget_across_the_stream(self) -> None:
        _, first_tile = self._add_insight_tile("$pageview")
        _, second_tile = self._add_insight_tile("$pageleave")
        clock = [0.0]
        attempts: list[int] = []

        @contextmanager
        def always_full(*args: Any, **kwargs: Any) -> Iterator[None]:
            attempts.append(1)
            clock[0] += 20
            if attempts:
                raise ConcurrencyLimitExceeded("Exceeded maximum concurrency limit")
            yield

        with (
            patch("posthog.hogql_queries.query_runner.app_org_concurrency_slot", side_effect=always_full),
            patch("products.dashboards.backend.query_sharing_stream.WORKERS_PER_STREAM", 1),
            patch("products.dashboards.backend.query_sharing_stream.CAPACITY_RETRY_DELAY_SECONDS", 0.01),
            patch("products.dashboards.backend.query_sharing_stream.monotonic", side_effect=lambda: clock[0]),
        ):
            events = self._stream([first_tile, second_tile])

        tile_events = [event for event in events if event["type"] == "tile"]
        self.assertEqual(len(tile_events), 2)
        for event in tile_events:
            self.assertEqual(event["tile"]["insight"]["query_status"]["error_code"], "rate_limited", event)
        # 10 seconds of budget from the first rejection: the first tile retries once, the second never.
        self.assertEqual(len(attempts), 3)
