from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic

from posthog.test.base import NonAtomicAPIBaseTest

from django.db import connection, connections, transaction

from rest_framework import status
from rest_framework.test import APIClient

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text


class TestDashboardTileConcurrency(NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _request(
        self,
        dashboard: Dashboard,
        payload: dict[str, object],
        backend: Queue[int],
        *,
        text_update: bool = False,
        after_lock: Callable[[], None] | None = None,
    ) -> int:
        conn = connections["default"]
        first_lock = True

        def trace_lock(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            nonlocal first_lock
            is_first_lock = first_lock and "FOR UPDATE" in sql and DashboardTile._meta.db_table in sql
            if is_first_lock:
                first_lock = False
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend.put(cursor.fetchone()[0])
            result = execute(sql, params, many, context)
            if is_first_lock and after_lock is not None:
                after_lock()
            return result

        try:
            client = APIClient()
            client.force_authenticate(self.user)
            with conn.execute_wrapper(trace_lock):
                url = f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/"
                response = (
                    client.post(f"{url}update_text_tile/", payload, format="json")
                    if text_update
                    else client.patch(url, payload, format="json")
                )
            return response.status_code
        finally:
            conn.close()

    def _wait_for_blocked_request(self, backend: int) -> None:
        deadline = monotonic() + 10
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [backend])
                if cursor.fetchone()[0]:
                    return
        self.fail("The request did not wait for a database lock.")

    def test_waiting_text_edit_reads_content_created_by_first_edit(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Destination")
        source = Dashboard.objects.create(team=self.team, name="Source")
        text = Text.objects.create(team=self.team, body="Original")
        tile = DashboardTile.objects.create(dashboard=dashboard, text=text)
        DashboardTile.objects.create(dashboard=source, text=text)
        backend: Queue[int] = Queue()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                DashboardTile.objects.select_for_update(of=("self",)).get(pk=tile.pk)
                pending = executor.submit(
                    self._request,
                    dashboard,
                    {"tile_id": tile.pk, "body": "Second edit"},
                    backend,
                    text_update=True,
                )
                self._wait_for_blocked_request(backend.get(timeout=10))
                response = self.client.post(
                    f"/api/projects/{self.team.id}/dashboards/{dashboard.id}/update_text_tile/",
                    {"tile_id": tile.pk, "body": "First edit"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(pending.result(timeout=15), status.HTTP_200_OK)

        tile.refresh_from_db()
        text.refresh_from_db()
        assert tile.text is not None
        self.assertEqual(tile.text.body, "Second edit")
        self.assertEqual(text.body, "Original")

    def test_batch_edits_with_opposite_tile_orders_both_complete(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Dashboard")
        texts = [Text.objects.create(team=self.team, body=f"Original {index}") for index in range(2)]
        tiles = [DashboardTile.objects.create(dashboard=dashboard, text=text) for text in texts]
        first_locked = Event()
        release_first = Event()
        first_backend: Queue[int] = Queue()
        second_backend: Queue[int] = Queue()

        def hold_first_lock() -> None:
            first_locked.set()
            self.assertTrue(release_first.wait(timeout=10))

        def payload(order: list[DashboardTile], body: str) -> dict[str, object]:
            return {"tiles": [{"id": tile.id, "text": {"id": tile.text_id, "body": body}} for tile in order]}

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                self._request, dashboard, payload(tiles, "First edit"), first_backend, after_lock=hold_first_lock
            )
            try:
                self.assertTrue(first_locked.wait(timeout=10))
                second = executor.submit(
                    self._request, dashboard, payload(list(reversed(tiles)), "Second edit"), second_backend
                )
                self._wait_for_blocked_request(second_backend.get(timeout=10))
            finally:
                release_first.set()
            self.assertEqual(first.result(timeout=15), status.HTTP_200_OK)
            self.assertEqual(second.result(timeout=15), status.HTTP_200_OK)

        for text in texts:
            text.refresh_from_db()
            self.assertEqual(text.body, "Second edit")
