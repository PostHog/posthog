import uuid
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypedDict, cast

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import connection
from django.test import override_settings

from parameterized import parameterized

from posthog.models import ActivityLog

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

if TYPE_CHECKING:
    # The test client's response type only exists in the stubs, and callers here read `.json()` off it.
    from rest_framework.response import _MonkeyPatchedResponse

# True defers the activity row to on_commit as production does; False is what every other test runs under.
DEFERRED_AND_IMMEDIATE = [("deferred", True), ("immediate", False)]


class SavedQueryResponse(TypedDict):
    id: str
    latest_history_id: str
    query: dict[str, Any]


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

    def _create(self) -> SavedQueryResponse:
        response = self.client.post(
            self._url(),
            {"name": "event_view", "query": {"kind": "HogQLQuery", "query": "select event from events limit 100"}},
        )
        self.assertEqual(response.status_code, 201, response.content)
        return cast(SavedQueryResponse, response.json())

    def _patch_query(self, view_id: str, sql: str, token: str | None) -> "_MonkeyPatchedResponse":
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

    def test_edit_that_lands_before_the_lock_is_rejected(self) -> None:
        created = self._create()
        token = created["latest_history_id"]
        other_revision = uuid.uuid4()
        take_lock = DataWarehouseSavedQuery.objects.select_for_update

        def commit_other_edit() -> None:
            # A thread gets its own connection, so this edit commits instead of joining the
            # request's transaction and rolling back with it.
            try:
                DataWarehouseSavedQuery.objects.filter(id=created["id"]).update(
                    query={"kind": "HogQLQuery", "query": "select uuid from events"},
                    query_revision=other_revision,
                )
            finally:
                connection.close()

        def edit_then_take_lock(*args: Any, **kwargs: Any) -> Any:
            # Land the other writer's edit after the view read the row and before this request locks
            # it. Only that ordering separates the locked row from the instance the view read, so a
            # conflict check reading the earlier instance would accept the token. The row carries no
            # lock yet, so the waiting writer cannot block here.
            other_writer = threading.Thread(target=commit_other_edit)
            other_writer.start()
            other_writer.join(timeout=30)
            self.assertFalse(other_writer.is_alive())
            return take_lock(*args, **kwargs)

        with patch.object(DataWarehouseSavedQuery.objects, "select_for_update", side_effect=edit_then_take_lock):
            response = self._patch_query(created["id"], "select event from events limit 10", token)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self._revision(created["id"]), str(other_revision))

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

    @parameterized.expand([("uppercase", str.upper), ("unhyphenated", lambda token: token.replace("-", ""))])
    def test_token_is_accepted_in_any_uuid_spelling(self, _name: str, reshape: Callable[[str], str]) -> None:
        created = self._create()

        response = self._patch_query(
            created["id"], "select event from events limit 10", reshape(created["latest_history_id"])
        )
        self.assertEqual(response.status_code, 200, response.content)

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
