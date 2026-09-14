import time
from datetime import timedelta
from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.ai_training_privacy import AITrainingPrivacyStore, DynamoResponse, item_key, session_key
from posthog.api.person import PersonViewSet
from posthog.models import Organization, Person, Team
from posthog.models.ai_training import (
    AITrainingConsent,
    AITrainingPrivacyRequest,
    queue_training_deletion,
    record_training_consent,
)
from posthog.models.team.util import delete_team_records
from posthog.tasks.ai_training_privacy import process_ai_training_privacy_requests


class TestAITrainingPrivacyStore(SimpleTestCase):
    @parameterized.expand([("disabled", "", False), ("enabled", "test-table", True)])
    def test_privacy_task_uses_dedicated_queue_and_only_drains_when_enabled(
        self, _name: str, table: str, enabled: bool
    ) -> None:
        with (
            self.settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE=table),
            patch("posthog.tasks.ai_training_privacy.AITrainingPrivacyStore.from_settings") as store,
        ):
            signature = process_ai_training_privacy_requests.signature()
            self.assertEqual(signature.type.queue, "ai_research_privacy")
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
            self.assertEqual(client.put_item.call_args.kwargs["Item"]["pk"]["S"], "month:2026-09")
            self.assertTrue(kwargs["ConsistentRead"])
            return pages.pop(0)

        client.query.side_effect = query
        store = AITrainingPrivacyStore(client, "table")
        self.assertEqual(store.delete_month("2026-09"), 2)
        self.assertEqual(
            [call.kwargs["TransactItems"][0]["Update"]["Key"] for call in client.transact_write_items.call_args_list],
            targets,
        )
        self.assertEqual(client.query.call_args_list[1].kwargs["ExclusiveStartKey"], cursor)
        self.assertEqual(client.query.call_count, 33)
        with self.assertRaises(ValueError):
            store.delete_month("2026-13")

    def test_withdrawal_preserves_keys_from_a_later_consent_period(self) -> None:
        client = MagicMock()
        old = {**item_key("team:7", "image:100"), "granted_at": {"N": "100"}, "wrapped_key": {"B": b"old"}}
        new = {**item_key("team:7", "image:300"), "granted_at": {"N": "300"}, "wrapped_key": {"B": b"new"}}
        client.query.return_value = {"Items": [old, new]}
        store = AITrainingPrivacyStore(client, "table")
        work = store.advance({"op": "team", "team_id": 7, "shard": -1, "withdrawn_at": 200})
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual([update["Update"]["Key"] for update in updates], [item_key("team:7", "image:100")])
        self.assertEqual(work, [{"op": "team", "team_id": 7, "shard": 0, "withdrawn_at": 200}])
        self.assertTrue(client.query.call_args.kwargs["ConsistentRead"])

    def test_distinct_deletion_shreds_each_session_and_removes_both_association_directions(self) -> None:
        client = MagicMock()
        sessions = ["01a09f92-e780-7000-8000-000000000001", "01a09f92-e780-7000-8000-000000000002"]
        client.query.return_value = {
            "Items": [item_key("team:7:distinct:digest:shard:0", f"session:{value}") for value in sessions]
        }
        store = AITrainingPrivacyStore(client, "table")
        next_work = store.advance({"op": "distinct", "team_id": 7, "digest": "digest", "shard": 0})
        updates = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual([update["Update"]["Key"] for update in updates], [session_key(7, value) for value in sessions])
        self.assertEqual([work["session_id"] for work in next_work if work["op"] == "associations"], sessions)
        client.query.return_value = {
            "Items": [
                {
                    **item_key(f"team:7:session:{sessions[0]}", "distinct:digest"),
                    "forward_pk": {"S": "team:7:distinct:digest:shard:0"},
                }
            ]
        }
        store.advance(next_work[0])
        deletions = client.transact_write_items.call_args.kwargs["TransactItems"]
        self.assertEqual(len(deletions), 2)
        self.assertEqual(
            deletions[1]["Delete"]["Key"], item_key("team:7:distinct:digest:shard:0", f"session:{sessions[0]}")
        )

    def test_completion_waits_for_reader_leases_without_sleeping_in_the_worker(self) -> None:
        request = MagicMock(kind="team", cursor={"work": []}, completed_at=None)
        store = AITrainingPrivacyStore(MagicMock(), "table")
        now = timezone.now()
        with patch("posthog.ai_training_privacy.timezone.now", return_value=now):
            self.assertFalse(store.apply(request, time.monotonic() + 1))
        self.assertIsNone(request.completed_at)
        with patch("posthog.ai_training_privacy.timezone.now", return_value=now + timedelta(seconds=301)):
            self.assertTrue(store.apply(request, time.monotonic() + 1))
        self.assertEqual(request.identifiers, [])


@override_settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE="test-table")
class TestAITrainingConsentOutbox(TestCase):
    @parameterized.expand([("",), ("test-table",)])
    def test_reconsent_has_a_new_timestamp_and_rollback_preserves_the_previous_state(self, table: str) -> None:
        with self.settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE=table):
            organization_id = UUID("00000000-0000-0000-0000-000000000007")
            with record_training_consent(organization_id, True):
                pass
            first = AITrainingConsent.objects.get(organization_id=organization_id)
            with record_training_consent(organization_id, False):
                pass
            with record_training_consent(organization_id, True):
                pass
            resumed = AITrainingConsent.objects.get(organization_id=organization_id)
            self.assertGreater(resumed.granted_at_ms, first.granted_at_ms)
            self.assertEqual(resumed.revision, 3)
            with self.assertRaises(ValueError), record_training_consent(organization_id, False):
                raise ValueError("rollback")
            self.assertTrue(AITrainingConsent.objects.get(organization_id=organization_id).allowed)
            self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 3)

    def test_deployment_initialization_preserves_existing_consent_and_is_safe_to_retry(self) -> None:
        existing_id = UUID("00000000-0000-0000-0000-000000000007")
        missing_id = UUID("00000000-0000-0000-0000-000000000008")
        denied_id = UUID("00000000-0000-0000-0000-000000000009")
        Organization.objects.bulk_create(
            [
                Organization(id=existing_id, name="Existing", slug="existing", is_ai_training_opted_in=True),
                Organization(id=missing_id, name="Missing", slug="missing", is_ai_training_opted_in=True),
                Organization(id=denied_id, name="Denied", slug="denied", is_ai_training_opted_in=False),
            ]
        )
        with self.settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE=""), record_training_consent(existing_id, True):
            pass
        existing = AITrainingConsent.objects.get(organization_id=existing_id)
        for _ in range(2):
            call_command("initialize_ai_training_consent")
            self.assertEqual(
                AITrainingConsent.objects.get(organization_id=existing_id).granted_at_ms, existing.granted_at_ms
            )
            self.assertTrue(AITrainingConsent.objects.get(organization_id=missing_id).allowed)
            self.assertFalse(AITrainingConsent.objects.get(organization_id=denied_id).allowed)
            self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 3)
        with record_training_consent(existing_id, False):
            Organization.objects.filter(id=existing_id).update(is_ai_training_opted_in=False)
        call_command("initialize_ai_training_consent")
        self.assertFalse(AITrainingConsent.objects.get(organization_id=existing_id).allowed)
        self.assertEqual(AITrainingPrivacyRequest.objects.unscoped().count(), 4)

    def test_queue_filters_invalid_session_ids_and_retains_distinct_ids_in_bulk(self) -> None:
        session_id = "01a09f92-e780-7000-8000-000000000001"
        queue_training_deletion(7, "session", ["invalid", session_id.upper(), session_id])
        request = AITrainingPrivacyRequest.objects.for_team(7).get()
        self.assertEqual(request.identifiers, [session_id])
        queue_training_deletion(7, "distinct", [f"distinct-{index}" for index in range(1001)])
        self.assertEqual(AITrainingPrivacyRequest.objects.for_team(7).filter(kind="distinct").count(), 2)

    @parameterized.expand([(False,), (True,)])
    def test_bulk_person_deletion_queues_resolved_and_unresolved_distinct_ids_once(self, keep_person: bool) -> None:
        person = Person(id=1, uuid=UUID("00000000-0000-0000-0000-000000000007"))
        person._distinct_ids = ["known", "alias"]
        view = MagicMock(team_id=7)
        request = MagicMock(user=None)
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()
        with (
            patch("posthog.api.person.resolve_persons_for_deletion", return_value=[person]),
            patch("posthog.models.person.bulk_delete._batched_get_distinct_ids_for_persons", return_value={}),
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres"),
            patch("posthog.models.person.bulk_delete.sync_connect", return_value=temporal),
        ):
            PersonViewSet._bulk_delete_persons(
                view,
                request,
                distinct_ids=["known", "missing"],
                delete_recordings=True,
                keep_person=keep_person,
            )
        queued = AITrainingPrivacyRequest.objects.for_team(7).get()
        self.assertEqual(queued.kind, "distinct")
        self.assertEqual(queued.identifiers, ["alias", "known", "missing"])

    def test_team_deletion_and_privacy_request_commit_together(self) -> None:
        with patch.object(Team, "objects") as teams:
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            teams.filter.return_value.delete.side_effect = RuntimeError("team delete failed")
            with self.assertRaisesRegex(RuntimeError, "team delete failed"):
                delete_team_records([7])
            self.assertFalse(AITrainingPrivacyRequest.objects.for_team(7).exists())

            teams.filter.return_value.delete.side_effect = None
            delete_team_records([7])
            self.assertEqual(AITrainingPrivacyRequest.objects.for_team(7).get().kind, "team")

    def test_team_deletion_does_not_run_if_privacy_request_write_fails(self) -> None:
        with (
            patch.object(Team, "objects") as teams,
            patch("django.db.models.query.QuerySet.bulk_create", side_effect=DatabaseError("outbox unavailable")),
        ):
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            with self.assertRaisesRegex(DatabaseError, "outbox unavailable"):
                delete_team_records([7])
            teams.filter.return_value.delete.assert_not_called()
