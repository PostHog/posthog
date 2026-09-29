import threading
from typing import Any

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection

from products.data_modeling.backend.facade import api as modeling_api
from products.data_modeling.backend.facade.models import DAG, DataWarehouseSavedQuery, Node

# Long enough that a move which is not blocked finishes inside it, short enough that the blocked
# case does not slow the suite down.
BLOCKED_MOVE_WINDOW_SECONDS = 2


class TestSavedQueryDagMoveConcurrency(NonAtomicAPIBaseTest):
    # TransactionTestCase, so a second connection sees what the request under test committed.
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(DataWarehouseSavedQuery, "get_columns", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _url(self, view_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/warehouse_saved_queries/"
        return f"{base}{view_id}" if view_id else base

    def test_a_move_cannot_land_between_a_query_edit_reading_a_placement_and_syncing_it(self) -> None:
        created = self.client.post(
            self._url(),
            {"name": "event_view", "query": {"kind": "HogQLQuery", "query": "select event from events limit 100"}},
        )
        self.assertEqual(created.status_code, 201, created.content)
        view = created.json()
        origin_dag_id = Node.objects.get(saved_query_id=view["id"]).dag_id
        destination = DAG.objects.create(team=self.team, name="Destination")

        def move_on_another_connection() -> None:
            # A thread gets its own connection, so this move commits instead of joining the
            # request's transaction and rolling back with it.
            try:
                modeling_api.move_saved_query_to_dag(self.team.pk, view["id"], destination.id)
            finally:
                connection.close()

        real_sync = modeling_api.sync_saved_query_to_dag
        movers: list[threading.Thread] = []

        def sync_after_a_move_tries_to_land(*args: Any, **kwargs: Any) -> Any:
            # The DAG to sync into was read just above this call, so this is the window where a
            # move that commits would leave the sync writing into the DAG the node has left --
            # and `get_or_create` would answer with a second node there.
            mover = threading.Thread(target=move_on_another_connection)
            mover.start()
            mover.join(timeout=BLOCKED_MOVE_WINDOW_SECONDS)
            movers.append(mover)
            self.assertTrue(mover.is_alive(), "the move was not held off by the request's row lock")
            return real_sync(*args, **kwargs)

        with patch(
            "products.data_modeling.backend.facade.api.sync_saved_query_to_dag",
            side_effect=sync_after_a_move_tries_to_land,
        ):
            response = self.client.patch(
                self._url(view["id"]),
                {
                    "query": {"kind": "HogQLQuery", "query": "select event from events limit 10"},
                    "edited_history_id": view["latest_history_id"],
                },
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(movers), 1)
        movers[0].join(timeout=30)
        self.assertFalse(movers[0].is_alive())

        nodes = list(Node.objects.filter(team=self.team, saved_query_id=view["id"]))
        self.assertEqual(len(nodes), 1)
        self.assertNotEqual(nodes[0].dag_id, origin_dag_id)
        self.assertEqual(nodes[0].dag_id, destination.id)
