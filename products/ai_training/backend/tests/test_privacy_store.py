import time
from datetime import datetime
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_training.backend.privacy.keys import DynamoResponse, item_key, session_key
from products.ai_training.backend.privacy.store import AITrainingPrivacyStore, V3KeyTarget
from products.ai_training.backend.privacy.v4 import V4KeyTarget
from products.ai_training.backend.tasks.tasks import process_ai_training_privacy_requests

NOW = "products.ai_training.backend.privacy.store.timezone.now"
TargetClass = type[V3KeyTarget] | type[V4KeyTarget]


def epoch(day: str) -> str:
    return str(int(datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp()))


class TestAITrainingPrivacyStore(SimpleTestCase):
    @parameterized.expand(
        [("disabled", "", "", False), ("v3", "test-table", "", True), ("v4", "", "test-v4-table", True)]
    )
    def test_privacy_task_uses_dedicated_queue_and_only_drains_when_enabled(
        self, _name: str, table: str, v4_table: str, enabled: bool
    ) -> None:
        with (
            self.settings(AI_RESEARCH_REPLAY_KEY_TABLE=table, AI_RESEARCH_V4_KEY_TABLE=v4_table),
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
        store = V3KeyTarget(client, "table")
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
        store = V3KeyTarget(client, "table")
        with patch(NOW, return_value=datetime.fromisoformat(now)):
            if allowed:
                self.assertEqual(store.delete_month(month), 0)
            else:
                with self.assertRaisesRegex(ValueError, "can be deleted from"):
                    store.delete_month(month)

    @parameterized.expand(
        [
            ("v3", V3KeyTarget, "SET deleted = :deleted REMOVE ", {":deleted": {"BOOL": True}}),
            (
                "v4",
                V4KeyTarget,
                "SET deleted = :true, expires_at = if_not_exists(expires_at, :expiry) REMOVE ",
                {":true": {"BOOL": True}, ":expiry": {"N": epoch("2027-03-01")}},
            ),
        ]
    )
    def test_session_deletion_shreds_every_key_attribute_without_querying_user_indexes(
        self, _name: str, target: TargetClass, prefix: str, values: dict[str, dict[str, object]]
    ) -> None:
        client = MagicMock()
        sessions = ["01a09f92-e780-7000-8000-000000000001", "01a09f92-e780-7000-8000-000000000002"]
        store = target(client, "table")
        with patch(NOW, return_value=datetime.fromisoformat("2026-10-31T23:59:00+00:00")):
            self.assertEqual(store.initialize(MagicMock(kind="session", team_id=7, identifiers=sessions)), [])
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual([update["Update"]["Key"] for update in updates], [session_key(7, value) for value in sessions])
        for update in updates:
            expression = update["Update"]["UpdateExpression"]
            self.assertTrue(expression.startswith(prefix))
            self.assertEqual(update["Update"]["ExpressionAttributeValues"], values)
            self.assertEqual(
                sorted(expression.partition(" REMOVE ")[2].split(", ")), ["key_nonce", "sealed_key", "wrapped_key"]
            )
        client.query.assert_not_called()

    @parameterized.expand(
        [
            (
                "v3",
                V3KeyTarget,
                [
                    (item_key("team:7", "image:2025-11"), None),
                    (item_key("team:7", "image:2025-12"), None),
                    (item_key("team:7", "image:2026-01"), None),
                ],
            ),
            (
                "v4",
                V4KeyTarget,
                [
                    (item_key("team:7", "month:2025-11"), {"N": epoch("2026-04-01")}),
                    (item_key("team:7", "month:2025-12"), {"N": epoch("2026-05-01")}),
                    (item_key("team:7", "month:2026-01"), {"N": epoch("2026-06-01")}),
                ],
            ),
        ]
    )
    def test_team_deletion_closes_every_month_a_later_session_could_still_open(
        self, _name: str, target: TargetClass, expected: list[tuple[object, object]]
    ) -> None:
        client = MagicMock()
        store = target(client, "table")
        with patch(NOW, return_value=datetime.fromisoformat("2025-12-31T23:59:00+00:00")):
            store.initialize(MagicMock(kind="team", team_id=7, identifiers=[]))
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(
            [
                (update["Update"]["Key"], update["Update"]["ExpressionAttributeValues"].get(":expiry"))
                for update in updates
            ],
            expected,
        )

    @parameterized.expand([("v3", V3KeyTarget), ("v4", V4KeyTarget)])
    def test_team_deletion_completes_in_one_pass_and_shreds_every_shard_it_sweeps(
        self, _name: str, target: TargetClass
    ) -> None:
        request = MagicMock(kind="team", team_id=7, identifiers=[], cursor={}, completed_at=None)
        late_write = session_key(7, "01a09f92-e780-7000-8000-000000000003")
        client = MagicMock()
        client.query.side_effect = [{"Items": []}, {"Items": [late_write]}, *({"Items": []} for _ in range(31))]
        store = AITrainingPrivacyStore([target(client, "table")])
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

    def test_request_with_both_targets_yields_at_the_deadline_and_resumes_each_target(self) -> None:
        request = MagicMock(kind="team", team_id=7, identifiers=[], cursor={}, completed_at=None)
        clock = MagicMock(return_value=0.0)

        def v3_query(**kwargs: Any) -> DynamoResponse:
            if kwargs["ExpressionAttributeValues"][":pk"] == {"S": "team:7:shard:31"}:
                clock.return_value = 2.0
            return {"Items": []}

        v3_client = MagicMock()
        v3_client.query.side_effect = v3_query
        v4_client = MagicMock()
        old_month = item_key("team:7", "month:2026-08")

        def v4_query(**kwargs: Any) -> DynamoResponse:
            if kwargs["ExpressionAttributeValues"][":pk"] == {"S": "team:7"} and "ExclusiveStartKey" not in kwargs:
                clock.return_value = 2.0
                return {"Items": [old_month], "LastEvaluatedKey": old_month}
            return {"Items": []}

        v4_client.query.side_effect = v4_query
        store = AITrainingPrivacyStore([V3KeyTarget(v3_client, "v3"), V4KeyTarget(v4_client, "v4")])
        with (
            patch(NOW, return_value=datetime.fromisoformat("2026-10-21T12:00:00+00:00")),
            patch("products.ai_training.backend.privacy.store.time.monotonic", clock),
        ):
            self.assertFalse(store.apply(request, 1.0))
            self.assertEqual(request.cursor["work"], [])
            self.assertNotIn("v4_work", request.cursor)
            v4_client.transact_write_items.assert_not_called()
            clock.return_value = 0.0
            self.assertFalse(store.apply(request, 1.0))
            self.assertIsNone(request.completed_at)
            self.assertEqual(request.cursor["v4_work"], [{"op": "team", "team_id": 7, "shard": -1, "after": old_month}])
            clock.return_value = 0.0
            self.assertTrue(store.apply(request, 1.0))
        self.assertIsNotNone(request.completed_at)
        self.assertEqual(v3_client.query.call_count, 33)
        self.assertEqual(v4_client.query.call_count, 34)
        self.assertEqual(v4_client.query.call_args_list[1].kwargs["ExclusiveStartKey"], old_month)
        tombstones = [
            (update["Update"]["Key"], update["Update"]["ExpressionAttributeValues"][":expiry"])
            for call in v4_client.transact_write_items.call_args_list
            for update in call.kwargs["TransactItems"]
        ]
        self.assertIn((old_month, {"N": epoch("2027-01-01")}), tombstones)

    def test_request_in_flight_with_only_v3_progress_resumes_v3_and_runs_v4_from_the_start(self) -> None:
        request = MagicMock(
            kind="team",
            team_id=7,
            identifiers=[],
            cursor={"work": [{"op": "team", "team_id": 7, "shard": 31}]},
            completed_at=None,
        )
        v3_client = MagicMock()
        v3_client.query.return_value = {"Items": []}
        v4_client = MagicMock()
        v4_client.query.return_value = {"Items": []}
        store = AITrainingPrivacyStore([V3KeyTarget(v3_client, "v3"), V4KeyTarget(v4_client, "v4")])
        with patch(NOW, return_value=datetime.fromisoformat("2026-10-21T12:00:00+00:00")):
            self.assertTrue(store.apply(request, time.monotonic() + 1))
        self.assertEqual(v3_client.query.call_count, 1)
        v3_client.transact_write_items.assert_not_called()
        self.assertEqual(v4_client.query.call_count, 33)
        self.assertEqual(
            [update["Update"]["Key"] for update in v4_client.transact_write_items.call_args.kwargs["TransactItems"]],
            [item_key("team:7", f"month:{month}") for month in ("2026-09", "2026-10", "2026-11")],
        )
        self.assertIsNotNone(request.completed_at)

    @parameterized.expand(
        [
            ("v3", "v3-table", "", [("v3-table", "us-east-1")]),
            ("v4", "", "v4-table", [("v4-table", "eu-west-1")]),
            ("both", "v3-table", "v4-table", [("v3-table", "us-east-1"), ("v4-table", "eu-west-1")]),
        ]
    )
    def test_store_runs_one_target_per_configured_table_with_its_own_client(
        self, _name: str, v3_table: str, v4_table: str, expected: list[tuple[str, str]]
    ) -> None:
        with (
            self.settings(
                AI_RESEARCH_REPLAY_KEY_TABLE=v3_table,
                AI_RESEARCH_REPLAY_AWS_REGION="us-east-1",
                AI_RESEARCH_V4_KEY_TABLE=v4_table,
                AI_RESEARCH_V4_AWS_REGION="eu-west-1",
            ),
            patch("products.ai_training.backend.privacy.keys.boto3.client") as client,
        ):
            store = AITrainingPrivacyStore.from_settings()
        self.assertEqual(
            [
                (target.table_name, call.kwargs["region_name"])
                for target, call in zip(store.targets, client.call_args_list, strict=True)
            ],
            expected,
        )
