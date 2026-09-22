from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from celery.exceptions import Retry
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.person import Person
from posthog.models.person.bulk_delete import PersonDeletionFailure, PersonDeletionStep, PersonProfileDeletionResult
from posthog.tasks.delete_persons import (
    REPUBLISH_MAX_RETRIES,
    PersonDeletionIncomplete,
    delete_persons_async,
    queue_person_deletion,
    republish_person_tombstones,
)


def _person() -> Person:
    return Person(uuid=uuid4(), team_id=1)


def _unpublished_reported(path: str) -> float:
    return REGISTRY.get_sample_value("posthog_person_deletion_unpublished_tombstones_total", {"path": path}) or 0.0


class TestQueuePersonDeletion(SimpleTestCase):
    def test_splits_persons_across_tasks(self) -> None:
        persons = [_person() for _ in range(3)]
        with (
            patch("posthog.tasks.delete_persons.PERSONS_PER_DELETION_TASK", 2),
            patch("posthog.tasks.delete_persons.delete_persons_async.delay") as delay,
        ):
            queued = queue_person_deletion(
                1,
                persons,
                delete_profile=True,
                delete_recordings=False,
                actor=None,
                request=None,
                organization_id=None,
                unmatched_distinct_ids=["ghost"],
            )
        assert queued == 3
        assert [len(call.kwargs["person_uuids"]) for call in delay.call_args_list] == [2, 1]
        assert [uuid for call in delay.call_args_list for uuid in call.kwargs["person_uuids"]] == [
            str(p.uuid) for p in persons
        ]
        # Unmatched distinct IDs ride on the first chunk only.
        assert [call.kwargs["unmatched_distinct_ids"] for call in delay.call_args_list] == [["ghost"], []]

    def test_queues_a_task_for_unmatched_distinct_ids_when_no_person_resolved(self) -> None:
        with patch("posthog.tasks.delete_persons.delete_persons_async.delay") as delay:
            queued = queue_person_deletion(
                1,
                [],
                delete_profile=True,
                delete_recordings=False,
                actor=None,
                request=None,
                organization_id=None,
                unmatched_distinct_ids=["ghost"],
            )
        assert queued == 0
        delay.assert_called_once()
        assert delay.call_args.kwargs["person_uuids"] == []
        assert delay.call_args.kwargs["unmatched_distinct_ids"] == ["ghost"]

    @parameterized.expand(
        [
            ("no_persons", [], True, True),
            ("nothing_to_do", [_person()], False, False),
        ]
    )
    def test_queues_nothing_when_there_is_no_work(
        self, _name: str, persons: list[Person], delete_profile: bool, delete_recordings: bool
    ) -> None:
        with patch("posthog.tasks.delete_persons.delete_persons_async.delay") as delay:
            queued = queue_person_deletion(
                1,
                persons,
                delete_profile=delete_profile,
                delete_recordings=delete_recordings,
                actor=None,
                request=None,
                organization_id=None,
            )
        assert queued == 0
        delay.assert_not_called()


class TestDeletePersonsAsync(SimpleTestCase):
    def _run(self, result: PersonProfileDeletionResult | Exception, retries: int = 0) -> None:
        with patch(
            "posthog.tasks.delete_persons.process_queued_person_deletion",
            side_effect=result if isinstance(result, Exception) else None,
            return_value=None if isinstance(result, Exception) else result,
        ):
            delete_persons_async.push_request(retries=retries)
            try:
                delete_persons_async.run(
                    team_id=1,
                    person_uuids=["a", "b"],
                    delete_profile=False,
                    delete_recordings=True,
                    actor_id=None,
                    organization_id="00000000-0000-0000-0000-00000000000a",
                    was_impersonated=True,
                    unmatched_distinct_ids=["ghost"],
                )
            finally:
                delete_persons_async.pop_request()

    @parameterized.expand([("last_attempt", 3, 1), ("earlier_attempt", 2, 0)])
    def test_reports_unpublished_tombstones_only_when_it_gives_up(
        self, _name: str, retries: int, reported: int
    ) -> None:
        result = PersonProfileDeletionResult(
            deleted_count=1,
            failures=[
                PersonDeletionFailure(
                    step=PersonDeletionStep.PUBLISH_CLICKHOUSE_TOMBSTONE, person_uuid=uuid4(), error="kafka"
                )
            ],
        )
        before = _unpublished_reported("queued")
        with patch.object(delete_persons_async, "retry", side_effect=Retry("retry")):
            with self.assertRaises(Retry):
                self._run(result, retries=retries)
        assert _unpublished_reported("queued") - before == reported

    def test_retries_only_the_failed_persons(self) -> None:
        failed = uuid4()
        result = PersonProfileDeletionResult(
            deleted_count=0,
            failures=[
                PersonDeletionFailure(
                    step=PersonDeletionStep.QUEUE_TRAINING_DELETION, person_uuid=failed, error="RuntimeError: x"
                )
            ],
        )
        with patch.object(delete_persons_async, "retry", side_effect=Retry("retry")) as retry:
            with self.assertRaises(Retry):
                self._run(result)
        kwargs = retry.call_args.kwargs["kwargs"]
        assert kwargs["person_uuids"] == [str(failed)]
        assert kwargs["delete_recordings"] is True
        assert kwargs["organization_id"] == "00000000-0000-0000-0000-00000000000a"
        assert kwargs["was_impersonated"] is True
        assert kwargs["unmatched_distinct_ids"] == []
        assert retry.call_args.kwargs["countdown"] == 60
        assert isinstance(retry.call_args.kwargs["exc"], PersonDeletionIncomplete)
        assert "queue_training_deletion=1" in str(retry.call_args.kwargs["exc"])

    def test_retries_the_unmatched_distinct_ids_when_their_training_step_failed(self) -> None:
        result = PersonProfileDeletionResult(
            deleted_count=0,
            failures=[
                PersonDeletionFailure(
                    step=PersonDeletionStep.QUEUE_TRAINING_DELETION, person_uuid=None, error="RuntimeError: x"
                )
            ],
        )
        with patch.object(delete_persons_async, "retry", side_effect=Retry("retry")) as retry:
            with self.assertRaises(Retry):
                self._run(result)
        kwargs = retry.call_args.kwargs["kwargs"]
        assert kwargs["person_uuids"] == []
        assert kwargs["unmatched_distinct_ids"] == ["ghost"]

    def test_retries_the_whole_chunk_when_the_task_crashes_before_recording_anything(self) -> None:
        crash = RuntimeError("database down")
        with patch.object(delete_persons_async, "retry", side_effect=Retry("retry")) as retry:
            with self.assertRaises(Retry):
                self._run(crash)
        assert retry.call_args.kwargs["exc"] is crash
        assert "kwargs" not in retry.call_args.kwargs

    def test_completes_quietly_when_all_deleted(self) -> None:
        with patch.object(delete_persons_async, "retry") as retry:
            self._run(PersonProfileDeletionResult(deleted_count=2))
        retry.assert_not_called()


class TestRepublishPersonTombstones(SimpleTestCase):
    def _run(self, still_unpublished: list, retries: int = 0) -> tuple:
        requested = [str(uuid4()), str(uuid4())]
        with (
            patch("posthog.tasks.delete_persons.republish_tombstones", return_value=still_unpublished) as republish,
            patch.object(republish_person_tombstones, "retry", side_effect=Retry("retry")) as retry,
        ):
            republish_person_tombstones.push_request(retries=retries)
            try:
                republish_person_tombstones.run(team_id=1, person_uuids=requested)
                raised = False
            except Retry:
                raised = True
            finally:
                republish_person_tombstones.pop_request()
        return republish, retry, raised

    def test_stops_when_everything_published(self) -> None:
        republish, retry, raised = self._run([])
        republish.assert_called_once()
        retry.assert_not_called()
        assert not raised

    @parameterized.expand([("first_attempt", 0, 60), ("past_the_deletion_retries", 3, 480), ("capped", 7, 1800)])
    def test_retries_with_only_the_unpublished_uuids(self, _name: str, retries: int, countdown: int) -> None:
        remaining = uuid4()
        _, retry, raised = self._run([remaining], retries=retries)
        assert raised
        assert retry.call_args.kwargs["kwargs"] == {"team_id": 1, "person_uuids": [str(remaining)]}
        assert retry.call_args.kwargs["countdown"] == countdown

    def test_gives_up_after_the_last_retry(self) -> None:
        before = _unpublished_reported("sync")
        _, retry, raised = self._run([uuid4()], retries=REPUBLISH_MAX_RETRIES)
        assert not raised
        retry.assert_not_called()
        assert _unpublished_reported("sync") - before == 1
