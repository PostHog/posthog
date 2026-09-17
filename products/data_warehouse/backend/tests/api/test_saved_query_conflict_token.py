from typing import Any, cast

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models import ActivityLog

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

# True defers the activity row to on_commit as production does; False is what every other test runs under.
DEFERRED_AND_IMMEDIATE = [("deferred", True), ("immediate", False)]


class TestSavedQueryConflictToken(NonAtomicAPIBaseTest):
    # TransactionTestCase, so the deferred activity row lands when the atomic block commits rather than never.
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(DataWarehouseSavedQuery, "get_columns", return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _url(self, view_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/warehouse_saved_queries/"
        return f"{base}{view_id}" if view_id else base

    def _create(self) -> dict:
        response = self.client.post(
            self._url(),
            {"name": "event_view", "query": {"kind": "HogQLQuery", "query": "select event from events limit 100"}},
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _patch_query(self, view_id: str, sql: str, token: str | None):
        return self.client.patch(
            self._url(view_id), {"query": {"kind": "HogQLQuery", "query": sql}, "edited_history_id": token}
        )

    def _revision(self, view_id: str) -> str | None:
        revision = DataWarehouseSavedQuery.objects.get(id=view_id).query_revision
        return str(revision) if revision else None

    @parameterized.expand(DEFERRED_AND_IMMEDIATE)
    def test_create_returns_a_usable_token(self, _name: str, deferred: bool) -> None:
        with override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=deferred):
            created = self._create()
            self.assertIsNotNone(created["latest_history_id"])
            self.assertEqual(created["latest_history_id"], self._revision(created["id"]))

            response = self._patch_query(
                created["id"], "select event from events limit 10", created["latest_history_id"]
            )
            self.assertEqual(response.status_code, 200, response.content)

    @parameterized.expand(DEFERRED_AND_IMMEDIATE)
    def test_update_returns_the_new_head_not_the_one_sent(self, _name: str, deferred: bool) -> None:
        with override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=deferred):
            created = self._create()
            token = created["latest_history_id"]

            response = self._patch_query(created["id"], "select event from events limit 10", token)
            self.assertEqual(response.status_code, 200, response.content)
            new_token = response.json()["latest_history_id"]
            self.assertNotEqual(new_token, token)
            self.assertEqual(new_token, self._revision(created["id"]))

            stale = self._patch_query(created["id"], "select event from events limit 5", token)
            self.assertEqual(stale.status_code, 400, stale.content)
            chained = self._patch_query(created["id"], "select event from events limit 5", new_token)
            self.assertEqual(chained.status_code, 200, chained.content)

    @parameterized.expand(DEFERRED_AND_IMMEDIATE)
    def test_non_query_update_keeps_the_token(self, _name: str, deferred: bool) -> None:
        with override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=deferred):
            created = self._create()
            token = created["latest_history_id"]

            # A cadence change writes its own activity row; a rename writes none and would prove nothing.
            response = self.client.patch(self._url(created["id"]), {"sync_frequency": "6hour"})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["latest_history_id"], token)

            chained = self._patch_query(created["id"], "select event from events limit 10", token)
            self.assertEqual(chained.status_code, 200, chained.content)

    def test_saving_the_same_query_keeps_the_token(self) -> None:
        created = self._create()
        token = created["latest_history_id"]

        response = self._patch_query(created["id"], created["query"]["query"], token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["latest_history_id"], token)

    def test_row_without_a_revision_accepts_any_token_once(self) -> None:
        created = self._create()
        DataWarehouseSavedQuery.objects.filter(id=created["id"]).update(query_revision=None)

        response = self._patch_query(created["id"], "select event from events limit 10", None)
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()["latest_history_id"]
        self.assertIsNotNone(token)

        stale = self._patch_query(created["id"], "select event from events limit 5", None)
        self.assertEqual(stale.status_code, 400, stale.content)

    def test_query_edit_does_not_record_the_revision_bump(self) -> None:
        created = self._create()

        response = self._patch_query(created["id"], "select event from events limit 10", created["latest_history_id"])
        self.assertEqual(response.status_code, 200, response.content)

        log = ActivityLog.objects.get(scope="DataWarehouseSavedQuery", item_id=created["id"], activity="updated")
        changed = [change["field"] for change in cast(dict[str, Any], log.detail)["changes"]]
        self.assertIn("query", changed)
        self.assertNotIn("query_revision", changed)
