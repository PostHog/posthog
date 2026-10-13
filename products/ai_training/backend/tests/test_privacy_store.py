import time
from datetime import datetime

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

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

    def test_month_deletion_shreds_all_index_pages_without_writing_a_block(self) -> None:
        client = MagicMock()
        cursor = item_key("month:2025-09:shard:0", "key:cursor")
        targets = [session_key(7, "01a09f92-e780-7000-8000-000000000001"), item_key("team:7", "image:1:2025-09")]
        pages: list[DynamoResponse] = []
        for index, target in enumerate(targets):
            page: DynamoResponse = {"Items": [{"key_pk": target["pk"], "key_sk": target["sk"]}]}
            if index == 0:
                page["LastEvaluatedKey"] = cursor
            pages.append(page)
        pages.extend({"Items": []} for _ in range(31))

        def query(**kwargs: object) -> DynamoResponse:
            self.assertTrue(kwargs["ConsistentRead"])
            return pages.pop(0)

        client.query.side_effect = query
        store = AITrainingPrivacyStore(client, "table")
        self.assertEqual(store.delete_month("2025-09"), 2)
        client.put_item.assert_not_called()
        self.assertEqual(
            [call.kwargs["TransactItems"][0]["Update"]["Key"] for call in client.transact_write_items.call_args_list],
            targets,
        )
        self.assertEqual(client.query.call_args_list[1].kwargs["ExclusiveStartKey"], cursor)
        self.assertEqual(client.query.call_count, 33)
        with self.assertRaises(ValueError):
            store.delete_month("2026-13")
        with self.assertRaises(ValueError):
            store.delete_month("9999-12")
        self.assertEqual(client.query.call_count, 33)

    @parameterized.expand(
        [
            ("2025-09", "2025-10-15T00:59:59+00:00", False),
            ("2025-09", "2025-10-15T01:00:00+00:00", True),
            ("2025-12", "2026-01-15T00:59:59+00:00", False),
            ("2025-12", "2026-01-15T01:00:00+00:00", True),
        ]
    )
    def test_month_deletion_opens_fourteen_days_and_one_hour_after_the_month_ends(
        self, month: str, now: str, allowed: bool
    ) -> None:
        client = MagicMock()
        client.query.return_value = {"Items": []}
        store = AITrainingPrivacyStore(client, "table")
        with patch("products.ai_training.backend.privacy.store.timezone.now", return_value=datetime.fromisoformat(now)):
            if allowed:
                self.assertEqual(store.delete_month(month), 0)
            else:
                with self.assertRaisesRegex(ValueError, "can be deleted from"):
                    store.delete_month(month)

    def test_session_deletion_shreds_every_key_attribute_without_querying_user_indexes(self) -> None:
        client = MagicMock()
        sessions = ["01a09f92-e780-7000-8000-000000000001", "01a09f92-e780-7000-8000-000000000002"]
        store = AITrainingPrivacyStore(client, "table")
        self.assertEqual(store.initialize(MagicMock(kind="session", team_id=7, identifiers=sessions)), [])
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual([update["Update"]["Key"] for update in updates], [session_key(7, value) for value in sessions])
        for update in updates:
            expression = update["Update"]["UpdateExpression"]
            self.assertTrue(expression.startswith("SET deleted = :deleted REMOVE "))
            self.assertEqual(update["Update"]["ExpressionAttributeValues"], {":deleted": {"BOOL": True}})
            self.assertEqual(
                sorted(expression.partition(" REMOVE ")[2].split(", ")), ["key_nonce", "sealed_key", "wrapped_key"]
            )
        client.query.assert_not_called()

    def test_team_deletion_closes_every_month_a_later_session_could_still_open(self) -> None:
        client = MagicMock()
        store = AITrainingPrivacyStore(client, "table")
        with patch(
            "products.ai_training.backend.privacy.store.timezone.now",
            return_value=datetime.fromisoformat("2025-12-31T23:59:00+00:00"),
        ):
            store.initialize(MagicMock(kind="team", team_id=7, identifiers=[]))
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(
            [update["Update"]["Key"] for update in updates],
            [
                item_key("team:7", "image:2025-11"),
                item_key("team:7", "image:2025-12"),
                item_key("team:7", "image:2026-01"),
            ],
        )

    def test_team_deletion_completes_in_one_pass_and_shreds_every_shard_it_sweeps(self) -> None:
        request = MagicMock(kind="team", team_id=7, identifiers=[], cursor={}, completed_at=None)
        late_write = session_key(7, "01a09f92-e780-7000-8000-000000000003")
        client = MagicMock()
        client.query.side_effect = [{"Items": []}, {"Items": [late_write]}, *({"Items": []} for _ in range(31))]
        store = AITrainingPrivacyStore(client, "table")
        self.assertTrue(store.apply(request, time.monotonic() + 1))
        self.assertEqual(client.query.call_count, 33)
        shredded = [
            update["Update"]["Key"]
            for call in client.transact_write_items.call_args_list
            for update in call.kwargs["TransactItems"]
        ]
        self.assertIn(late_write, shredded)
        self.assertIsNotNone(request.completed_at)
        self.assertEqual(request.identifiers, [])
