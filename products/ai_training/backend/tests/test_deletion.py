from uuid import UUID

from unittest.mock import AsyncMock, MagicMock, patch

from django.db import DatabaseError
from django.test import TestCase, override_settings

from parameterized import parameterized

from posthog.api.person import PersonViewSet
from posthog.models import Person, Team
from posthog.models.team.util import delete_team_records

from products.ai_training.backend.facade.api import queue_person_training_deletion, queue_training_deletion
from products.ai_training.backend.models import AITrainingDeletionRequest


@override_settings(AI_RESEARCH_REPLAY_PRIVACY_TABLE="test-table")
class TestAITrainingDeletionOutbox(TestCase):
    def test_queue_filters_invalid_session_ids_and_batches_valid_sessions(self) -> None:
        session_id = "01a09f92-e780-7000-8000-000000000001"
        queue_training_deletion(7, "session", ["invalid", session_id.upper(), session_id])
        request = AITrainingDeletionRequest.objects.for_team(7).get()
        self.assertEqual(request.identifiers, [session_id])
        queue_training_deletion(7, "session", [f"01a09f92-e780-7000-8000-{index:012x}" for index in range(1001)])
        self.assertEqual(AITrainingDeletionRequest.objects.for_team(7).count(), 3)

    @parameterized.expand([(False, False), (False, True), (True, True)])
    def test_bulk_person_deletion_resolves_all_ids_and_queues_only_sessions(
        self, keep_person: bool, delete_recordings: bool
    ) -> None:
        person = Person(id=1, uuid=UUID("00000000-0000-0000-0000-000000000007"))
        person._distinct_ids = ["known", "alias"]
        view = MagicMock(team_id=7)
        request = MagicMock(user=None)
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()
        session_id = "01a09f92-e780-7000-8000-000000000001"
        with (
            patch("products.ai_training.backend.logic.deletion.Team.objects.get", return_value=Team(id=7)),
            patch(
                "posthog.hogql.query.execute_hogql_query",
                return_value=MagicMock(results=[[session_id]]),
            ) as lookup,
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
                delete_recordings=delete_recordings,
                keep_person=keep_person,
            )
        queued = AITrainingDeletionRequest.objects.for_team(7).get()
        self.assertEqual(queued.kind, "session")
        self.assertEqual(queued.identifiers, [session_id])
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(lookup.call_args.kwargs["team"].id, 7)
        self.assertEqual(
            [value.value for value in lookup.call_args.kwargs["placeholders"]["distinct_ids"].exprs],
            ["alias", "known", "missing"],
        )

    def test_person_lookup_paginates_without_storing_user_ids(self) -> None:
        sessions = [f"01a09f92-e780-7000-8000-{index:012x}" for index in range(1001)]
        with (
            patch("products.ai_training.backend.logic.deletion.Team.objects.get", return_value=Team(id=7)),
            patch(
                "posthog.hogql.query.execute_hogql_query",
                side_effect=[
                    MagicMock(results=[[value] for value in sessions[:1000]]),
                    MagicMock(results=[[sessions[-1]]]),
                ],
            ) as lookup,
        ):
            queue_person_training_deletion(7, ["user@example.com"])
        identifiers = [
            value for request in AITrainingDeletionRequest.objects.for_team(7).all() for value in request.identifiers
        ]
        self.assertEqual(sorted(identifiers), sessions)
        self.assertEqual(lookup.call_args.kwargs["placeholders"]["cursor"].value, sessions[999])
        self.assertEqual(AITrainingDeletionRequest.objects.for_team(7).count(), 2)

    def test_team_deletion_and_deletion_request_commit_together(self) -> None:
        with patch.object(Team, "objects") as teams:
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            teams.filter.return_value.delete.side_effect = RuntimeError("team delete failed")
            with self.assertRaisesRegex(RuntimeError, "team delete failed"):
                delete_team_records([7])
            self.assertFalse(AITrainingDeletionRequest.objects.for_team(7).exists())

            teams.filter.return_value.delete.side_effect = None
            delete_team_records([7])
            self.assertEqual(AITrainingDeletionRequest.objects.for_team(7).get().kind, "team")

    def test_team_deletion_does_not_run_if_deletion_request_write_fails(self) -> None:
        with (
            patch.object(Team, "objects") as teams,
            patch("django.db.models.query.QuerySet.bulk_create", side_effect=DatabaseError("outbox unavailable")),
        ):
            teams.select_for_update.return_value.filter.return_value = [Team(id=7)]
            with self.assertRaisesRegex(DatabaseError, "outbox unavailable"):
                delete_team_records([7])
            teams.filter.return_value.delete.assert_not_called()
