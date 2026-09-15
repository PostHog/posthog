import time
from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.ai_training.backend.privacy.store import AITrainingPrivacyStore, DynamoResponse, item_key, session_key
from products.ai_training.backend.tasks.tasks import process_ai_training_privacy_requests


class TestAITrainingPrivacyStore(SimpleTestCase):
    @parameterized.expand([("disabled", "", False), ("enabled", "test-table", True)])
    def test_privacy_task_uses_dedicated_queue_and_only_drains_when_enabled(
        self, _name: str, table: str, enabled: bool
    ) -> None:
        with (
            self.settings(AI_RESEARCH_REPLAY_KEY_TABLE=table),
            patch("products.ai_training.backend.tasks.tasks.AITrainingPrivacyStore.from_settings") as store,
        ):
            signature = process_ai_training_privacy_requests.signature()
            self.assertEqual(signature.type.queue, "ai_research_privacy")
            self.assertEqual(
                signature.type.name, "posthog.tasks.ai_training_privacy.process_ai_training_privacy_requests"
            )
            signature.apply().get()
            self.assertEqual(store.called, enabled)
            self.assertEqual(store.return_value.drain.called, enabled)

    def test_month_deletion_blocks_before_querying_and_shreds_all_index_pages(self) -> None:
        client = MagicMock()
        cursor = item_key("month:2026-09:shard:0", "key:cursor")
        targets = [session_key(7, "01a09f92-e780-7000-8000-000000000001"), item_key("team:7", "image:1:2026-09")]
        pages: list[DynamoResponse] = []
        for index, target in enumerate(targets):
            page: DynamoResponse = {"Items": [{"key_pk": target["pk"], "key_sk": target["sk"]}]}
            if index == 0:
                page["LastEvaluatedKey"] = cursor
            pages.append(page)
        pages.extend({"Items": []} for _ in range(31))

        def query(**kwargs: object) -> DynamoResponse:
            markers = client.transact_write_items.call_args_list[0].kwargs["TransactItems"]
            self.assertEqual(markers[0]["Put"]["Item"]["pk"]["S"], "month:2026-09")
            self.assertTrue(kwargs["ConsistentRead"])
            return pages.pop(0)

        client.query.side_effect = query
        store = AITrainingPrivacyStore(client, "table")
        self.assertEqual(store.delete_month("2026-09"), 2)
        self.assertEqual(
            [
                call.kwargs["TransactItems"][0]["Update"]["Key"]
                for call in client.transact_write_items.call_args_list[1:]
            ],
            targets,
        )
        self.assertEqual(client.query.call_args_list[1].kwargs["ExclusiveStartKey"], cursor)
        self.assertEqual(client.query.call_count, 33)
        with self.assertRaises(ValueError):
            store.delete_month("2026-13")

    @parameterized.expand([("team", "team:7"), ("month", "month:2026-09")])
    def test_block_markers_cover_every_shard(self, kind: str, pk: str) -> None:
        client = MagicMock()
        client.query.return_value = {"Items": []}
        store = AITrainingPrivacyStore(client, "table")
        if kind == "team":
            store.initialize(MagicMock(kind="team", team_id=7))
        else:
            store.delete_month("2026-09")
        markers = client.transact_write_items.call_args_list[0].kwargs["TransactItems"]
        self.assertEqual(
            [marker["Put"]["Item"]["pk"]["S"] for marker in markers],
            [pk, *(f"{pk}:shard:{shard}" for shard in range(32))],
        )
        self.assertTrue(
            all(
                marker["Put"]["Item"]["sk"]["S"] == "deleted" and marker["Put"]["Item"]["deleted"]["BOOL"] is True
                for marker in markers
            )
        )

    def test_session_deletion_shreds_keys_without_querying_user_indexes(self) -> None:
        client = MagicMock()
        sessions = ["01a09f92-e780-7000-8000-000000000001", "01a09f92-e780-7000-8000-000000000002"]
        store = AITrainingPrivacyStore(client, "table")
        self.assertEqual(store.initialize(MagicMock(kind="session", team_id=7, identifiers=sessions)), [])
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual([update["Update"]["Key"] for update in updates], [session_key(7, value) for value in sessions])
        self.assertTrue(
            all(
                update["Update"]["UpdateExpression"] == "SET deleted = :deleted REMOVE wrapped_key"
                for update in updates
            )
        )
        client.query.assert_not_called()

    def test_completion_waits_for_reader_leases_without_sleeping_in_the_worker(self) -> None:
        request = MagicMock(kind="team", cursor={"work": []}, completed_at=None)
        store = AITrainingPrivacyStore(MagicMock(), "table")
        now = timezone.now()
        with patch("products.ai_training.backend.privacy.store.timezone.now", return_value=now):
            self.assertFalse(store.apply(request, time.monotonic() + 1))
        self.assertIsNone(request.completed_at)
        with patch(
            "products.ai_training.backend.privacy.store.timezone.now", return_value=now + timedelta(seconds=301)
        ):
            self.assertTrue(store.apply(request, time.monotonic() + 1))
        self.assertEqual(request.identifiers, [])
