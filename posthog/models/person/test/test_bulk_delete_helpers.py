from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
from posthog.models.person.bulk_delete import (
    delete_persons_profile,
    queue_person_event_deletion,
    queue_person_recording_deletion,
    resolve_persons_for_deletion,
)


class ResolvePersonsTests(BaseTest):
    def test_resolves_by_uuid(self):
        p = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=[str(p.uuid)], distinct_ids=None)
        assert [r.uuid for r in result] == [p.uuid]

    def test_resolves_by_distinct_id(self):
        p = Person.objects.create(team=self.team, distinct_ids=["did-x"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=None, distinct_ids=["did-x"])
        assert [r.uuid for r in result] == [p.uuid]

    def test_resolves_by_mixed_inputs(self):
        p1 = Person.objects.create(team=self.team, distinct_ids=["d1"], properties={})
        p2 = Person.objects.create(team=self.team, distinct_ids=["d2"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=[str(p1.uuid)], distinct_ids=["d2"])
        assert {r.uuid for r in result} == {p1.uuid, p2.uuid}

    def test_returns_empty_when_neither(self):
        assert resolve_persons_for_deletion(self.team.pk, uuids=None, distinct_ids=None) == []


class QueueEventDeletionTests(BaseTest):
    def test_creates_one_async_deletion_per_person(self):
        p = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        assert (
            AsyncDeletion.objects.filter(
                team_id=self.team.pk, deletion_type=DeletionType.Person, key=str(p.uuid)
            ).count()
            == 1
        )

    def test_ignores_duplicate_queueing(self):
        p = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        assert AsyncDeletion.objects.filter(team_id=self.team.pk).count() == 1


class DeletePersonsProfileTests(BaseTest):
    def test_deletes_persons_via_helpers(self):
        p = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)
        assert result.deleted_count == 1
        assert result.errors == []
        ch_delete.assert_called_once_with(person=p)
        pg_delete.assert_called_once_with(self.team.pk, [p])

    def test_collects_errors_and_skips_failed_persons_in_pg_batch(self):
        p1 = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        p2 = Person.objects.create(team=self.team, distinct_ids=["b"], properties={})
        with (
            patch(
                "posthog.models.person.bulk_delete.delete_person",
                side_effect=[None, RuntimeError("boom")],
            ),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = delete_persons_profile(self.team.pk, [p1, p2], actor=self.user)
        assert result.deleted_count == 1
        assert [str(e) for e in result.errors] == [str(p2.uuid)]
        pg_delete.assert_called_once_with(self.team.pk, [p1])


class QueueRecordingDeletionTests(BaseTest):
    def test_skips_when_no_persons(self):
        with patch("posthog.models.person.bulk_delete.sync_connect") as conn:
            queue_person_recording_deletion(self.team.pk, [], actor=self.user)
            conn.assert_not_called()

    def test_starts_workflow_per_person(self):
        p1 = Person.objects.create(team=self.team, distinct_ids=["a"], properties={})
        p2 = Person.objects.create(team=self.team, distinct_ids=["b"], properties={})
        with patch("posthog.models.person.bulk_delete._start_recording_workflows") as start:
            queue_person_recording_deletion(self.team.pk, [p1, p2], actor=self.user)
            start.assert_called_once()
            (_, persons, _, _) = start.call_args.args
            assert {p.uuid for p in persons} == {p1.uuid, p2.uuid}
