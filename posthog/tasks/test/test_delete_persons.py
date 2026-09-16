from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models.person import Person
from posthog.models.person.bulk_delete import PersonProfileDeletionResult
from posthog.tasks.delete_persons import (
    PersonDeletionIncomplete,
    delete_persons_profile_async,
    queue_person_profile_deletion,
)


def _person() -> Person:
    return Person(uuid=uuid4(), team_id=1)


class TestQueuePersonProfileDeletion(SimpleTestCase):
    def test_splits_persons_across_tasks(self) -> None:
        persons = [_person() for _ in range(3)]
        with (
            patch("posthog.tasks.delete_persons.PERSONS_PER_DELETION_TASK", 2),
            patch("posthog.tasks.delete_persons.delete_persons_profile_async.delay") as delay,
        ):
            queued = queue_person_profile_deletion(1, persons, actor=None, request=None, organization_id=None)
        assert queued == 3
        assert [len(call.kwargs["person_uuids"]) for call in delay.call_args_list] == [2, 1]
        assert [uuid for call in delay.call_args_list for uuid in call.kwargs["person_uuids"]] == [
            str(p.uuid) for p in persons
        ]

    def test_queues_nothing_for_no_persons(self) -> None:
        with patch("posthog.tasks.delete_persons.delete_persons_profile_async.delay") as delay:
            assert queue_person_profile_deletion(1, [], actor=None, request=None, organization_id=None) == 0
        delay.assert_not_called()


class TestDeletePersonsProfileAsync(SimpleTestCase):
    def test_raises_when_some_persons_failed_so_celery_retries(self) -> None:
        with patch(
            "posthog.tasks.delete_persons.delete_persons_profile_by_uuids",
            return_value=PersonProfileDeletionResult(deleted_count=1, errors=[uuid4()]),
        ):
            with self.assertRaises(PersonDeletionIncomplete):
                delete_persons_profile_async.run(
                    team_id=1, person_uuids=["a", "b"], actor_id=None, organization_id=None, was_impersonated=False
                )

    def test_completes_quietly_when_all_deleted(self) -> None:
        with patch(
            "posthog.tasks.delete_persons.delete_persons_profile_by_uuids",
            return_value=PersonProfileDeletionResult(deleted_count=2),
        ):
            delete_persons_profile_async.run(
                team_id=1, person_uuids=["a", "b"], actor_id=None, organization_id=None, was_impersonated=False
            )
