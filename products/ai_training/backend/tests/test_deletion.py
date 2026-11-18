from datetime import UTC, datetime, timedelta
from uuid import UUID

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import DatabaseError
from django.test import TestCase, override_settings

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.api.person import PersonViewSet
from posthog.exceptions import ClickHouseAtCapacity
from posthog.models import Person, Team
from posthog.models.team.util import delete_team_records
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.uuidt import uuid7

from products.ai_training.backend.facade.api import queue_person_training_deletion, queue_training_deletion
from products.ai_training.backend.logic.deletion import resolve_person_training_sessions
from products.ai_training.backend.models import AITrainingDeletionRequest
from products.ai_training.backend.tasks.tasks import (
    PERSON_LOOKUP_MAX_RETRIES,
    person_lookup_retry_countdown,
    resolve_person_training_sessions_task,
)

# The Redis broker redelivers a message that a worker holds longer than this.
BROKER_VISIBILITY_TIMEOUT_SECONDS = 3600


def _teams(team: Team) -> MagicMock:
    return MagicMock(first=MagicMock(return_value=team))


def _apply_lookup_task(retries: int) -> None:
    resolve_person_training_sessions_task.apply(
        args=(7, ["known"], datetime.now(UTC).isoformat()), retries=retries, throw=True
    )


@override_settings(AI_RESEARCH_REPLAY_KEY_TABLE="test-table")
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
        view = MagicMock(team_id=7, organization=MagicMock(id=UUID("00000000-0000-0000-0000-00000000000a")))
        request = MagicMock(user=None)
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()
        session_id = "01a09f92-e780-7000-8000-000000000001"
        with (
            patch("products.ai_training.backend.logic.deletion.Team.objects.filter", return_value=_teams(Team(id=7))),
            patch(
                "posthog.hogql.query.execute_hogql_query",
                return_value=MagicMock(results=[[session_id]]),
            ) as lookup,
            patch("posthog.api.person.resolve_persons_for_deletion", return_value=[person]),
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
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
            patch("products.ai_training.backend.logic.deletion.Team.objects.filter", return_value=_teams(Team(id=7))),
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

    def test_person_deletion_queues_the_lookup_instead_of_waiting_on_clickhouse(self) -> None:
        person = Person(id=1, uuid=UUID("00000000-0000-0000-0000-000000000007"))
        person._distinct_ids = ["known", "alias"]
        view = MagicMock(team_id=7, organization=MagicMock(id=UUID("00000000-0000-0000-0000-00000000000a")))
        with (
            patch("posthog.hogql.query.execute_hogql_query", side_effect=ClickHouseAtCapacity()) as lookup,
            patch.object(resolve_person_training_sessions_task, "delay") as enqueue,
            patch("posthog.api.person.resolve_persons_for_deletion", return_value=[person]),
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
        ):
            summary = PersonViewSet._bulk_delete_persons(view, MagicMock(user=None), distinct_ids=["known", "missing"])
        self.assertEqual(summary["deletion_errors"], [])
        lookup.assert_not_called()
        enqueue.assert_called_once()
        team_id, distinct_ids, started_before = enqueue.call_args.args
        self.assertEqual((team_id, distinct_ids), (7, ["alias", "known", "missing"]))
        self.assertLess(datetime.now(UTC) - datetime.fromisoformat(started_before), timedelta(minutes=1))

    @parameterized.expand(
        [
            ("first_failure_retries", 0, ClickHouseAtCapacity(), Retry),
            ("last_failure_gives_up", PERSON_LOOKUP_MAX_RETRIES, ClickHouseAtCapacity(), ClickHouseAtCapacity),
            ("retry_succeeds", 3, MagicMock(results=[["01a09f92-e780-7000-8000-000000000001"]]), None),
        ]
    )
    def test_person_lookup_retries_a_busy_cluster_until_its_budget_runs_out(
        self, _name: str, retries: int, response: object, raised: type[BaseException] | None
    ) -> None:
        with (
            patch("products.ai_training.backend.logic.deletion.Team.objects.filter", return_value=_teams(Team(id=7))),
            patch("posthog.hogql.query.execute_hogql_query", side_effect=[response]),
        ):
            if raised is None:
                _apply_lookup_task(retries)
            elif raised is Retry:
                with self.assertRaises(Retry) as retry:
                    _apply_lookup_task(retries)
                scheduled: Retry = retry.exception
                self.assertEqual(scheduled.when, person_lookup_retry_countdown(retries))
            else:
                with self.assertRaises(raised):
                    _apply_lookup_task(retries)
        queued = list(AITrainingDeletionRequest.objects.for_team(7).values_list("identifiers", flat=True))
        self.assertEqual(queued, [] if raised else [["01a09f92-e780-7000-8000-000000000001"]])

    def test_person_lookup_retries_for_a_day_without_outliving_the_broker_visibility_timeout(self) -> None:
        countdowns = [person_lookup_retry_countdown(retries) for retries in range(PERSON_LOOKUP_MAX_RETRIES)]
        self.assertLess(max(countdowns), BROKER_VISIBILITY_TIMEOUT_SECONDS)
        self.assertGreaterEqual(sum(countdowns), 24 * 3600)

    def test_person_lookup_runs_on_a_queue_with_clickhouse_access(self) -> None:
        # The ai_research_privacy worker has restricted grants and no ClickHouse access.
        self.assertEqual(resolve_person_training_sessions_task.signature().type.queue, "long_running")

    def test_person_lookup_for_a_deleted_team_finishes_without_a_lookup(self) -> None:
        with patch("posthog.hogql.query.execute_hogql_query") as lookup:
            resolve_person_training_sessions(987654, ["known"], datetime.now(UTC))
        lookup.assert_not_called()
        self.assertFalse(AITrainingDeletionRequest.objects.for_team(987654).exists())

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


@override_settings(AI_RESEARCH_REPLAY_KEY_TABLE="test-table")
class TestPersonTrainingSessionLookup(ClickhouseTestMixin, BaseTest):
    def test_resolves_sessions_that_started_before_the_deletion_including_deleted_recordings(self) -> None:
        deleted_at = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
        before, deleted_recording, after, other_person = (str(uuid7()) for _ in range(4))
        for session_id, distinct_id, started_at, is_deleted in [
            (before, "known", deleted_at - timedelta(hours=1), False),
            (deleted_recording, "known", deleted_at - timedelta(days=1), True),
            (after, "known", deleted_at + timedelta(minutes=5), False),
            (other_person, "someone-else", deleted_at - timedelta(hours=1), False),
        ]:
            produce_replay_summary(
                team_id=self.team.pk,
                session_id=session_id,
                distinct_id=distinct_id,
                first_timestamp=started_at,
                last_timestamp=started_at + timedelta(minutes=1),
                is_deleted=is_deleted,
                ensure_analytics_event_in_session=False,
            )

        resolve_person_training_sessions(self.team.pk, ["known"], deleted_at)

        queued = AITrainingDeletionRequest.objects.for_team(self.team.pk).get()
        self.assertEqual(queued.identifiers, sorted([before, deleted_recording]))
