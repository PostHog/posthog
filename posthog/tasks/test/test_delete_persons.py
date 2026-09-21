from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.models.person import Person
from posthog.models.person.bulk_delete import PersonDeletionFailure, PersonDeletionStep, PersonProfileDeletionResult
from posthog.tasks.delete_persons import PersonDeletionIncomplete, delete_persons_async, queue_person_deletion


def _person() -> Person:
    return Person(uuid=uuid4(), team_id=1)


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
    def _run(self, result: PersonProfileDeletionResult | Exception) -> None:
        with patch(
            "posthog.tasks.delete_persons.process_queued_person_deletion",
            side_effect=result if isinstance(result, Exception) else None,
            return_value=None if isinstance(result, Exception) else result,
        ):
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
