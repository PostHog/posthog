from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person import Person
from posthog.models.person.bulk_delete import PersonDeletionFailure, PersonDeletionStep, PersonProfileDeletionResult
from posthog.tasks.delete_persons import (
    MAX_DELETION_ATTEMPTS,
    PersonDeletionIncomplete,
    delete_persons_async,
    queue_person_deletion,
)


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
                1, persons, delete_profile=True, delete_recordings=False, actor=None, request=None, organization_id=None
            )
        assert queued == 3
        assert [len(call.kwargs["person_uuids"]) for call in delay.call_args_list] == [2, 1]
        assert [uuid for call in delay.call_args_list for uuid in call.kwargs["person_uuids"]] == [
            str(p.uuid) for p in persons
        ]

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
    def _run(self, result: PersonProfileDeletionResult, attempt: int) -> None:
        with patch("posthog.tasks.delete_persons.process_queued_person_deletion", return_value=result):
            delete_persons_async.run(
                team_id=1,
                person_uuids=["a", "b"],
                delete_profile=False,
                delete_recordings=True,
                actor_id=None,
                organization_id="00000000-0000-0000-0000-00000000000a",
                was_impersonated=True,
                attempt=attempt,
            )

    def test_requeues_only_the_failed_persons(self) -> None:
        failed = uuid4()
        result = PersonProfileDeletionResult(
            deleted_count=0,
            failures=[
                PersonDeletionFailure(
                    step=PersonDeletionStep.QUEUE_TRAINING_DELETION, person_uuid=failed, error="RuntimeError: x"
                )
            ],
        )
        with patch("posthog.tasks.delete_persons.delete_persons_async.apply_async") as requeue:
            self._run(result, attempt=1)
        requeue.assert_called_once()
        kwargs = requeue.call_args.kwargs["kwargs"]
        assert kwargs["person_uuids"] == [str(failed)]
        assert kwargs["attempt"] == 2
        assert kwargs["delete_recordings"] is True
        assert kwargs["organization_id"] == "00000000-0000-0000-0000-00000000000a"
        assert kwargs["was_impersonated"] is True
        assert requeue.call_args.kwargs["countdown"] == 60

    def test_gives_up_after_the_last_attempt(self) -> None:
        result = PersonProfileDeletionResult(
            deleted_count=1,
            failures=[
                PersonDeletionFailure(
                    step=PersonDeletionStep.FETCH_DISTINCT_IDS, person_uuid=uuid4(), error="RuntimeError: x"
                )
            ],
        )
        with patch("posthog.tasks.delete_persons.delete_persons_async.apply_async") as requeue:
            with self.assertRaises(PersonDeletionIncomplete) as raised:
                self._run(result, attempt=MAX_DELETION_ATTEMPTS)
        requeue.assert_not_called()
        assert "fetch_distinct_ids=1" in str(raised.exception)

    def test_completes_quietly_when_all_deleted(self) -> None:
        with patch("posthog.tasks.delete_persons.delete_persons_async.apply_async") as requeue:
            self._run(PersonProfileDeletionResult(deleted_count=2), attempt=1)
        requeue.assert_not_called()
