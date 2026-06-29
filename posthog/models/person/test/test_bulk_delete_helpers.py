from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
from posthog.models.person.bulk_delete import (
    _start_recording_workflows,
    delete_persons_profile,
    queue_person_event_deletion,
    queue_person_recording_deletion,
    resolve_persons_for_deletion,
)
from posthog.test.persons import create_person


def _person_with_distinct_ids(*distinct_ids: str) -> Person:
    # Unsaved Person with its distinct_ids cached, mirroring how production callers
    # pre-resolve them — so reads stay in-memory inside the async fan-out.
    person = Person()
    person._distinct_ids = list(distinct_ids)
    return person


class ResolvePersonsTests(BaseTest):
    def test_resolves_by_uuid(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=[str(p.uuid)], distinct_ids=None)
        assert [r.uuid for r in result] == [p.uuid]

    def test_resolves_by_distinct_id(self):
        p = create_person(team=self.team, distinct_ids=["did-x"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=None, distinct_ids=["did-x"])
        assert [r.uuid for r in result] == [p.uuid]

    def test_uuids_take_precedence_over_distinct_ids(self):
        p1 = create_person(team=self.team, distinct_ids=["d1"], properties={})
        create_person(team=self.team, distinct_ids=["d2"], properties={})
        result = resolve_persons_for_deletion(self.team.pk, uuids=[str(p1.uuid)], distinct_ids=["d2"])
        assert {r.uuid for r in result} == {p1.uuid}

    def test_resolved_person_has_distinct_ids(self):
        p = create_person(team=self.team, distinct_ids=["a", "b"], properties={})
        [resolved] = resolve_persons_for_deletion(self.team.pk, uuids=[str(p.uuid)], distinct_ids=None)
        assert sorted(resolved.distinct_ids) == ["a", "b"]

    def test_returns_empty_when_neither(self):
        assert resolve_persons_for_deletion(self.team.pk, uuids=None, distinct_ids=None) == []


class QueueEventDeletionTests(BaseTest):
    def test_creates_one_async_deletion_per_person(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        assert (
            AsyncDeletion.objects.filter(
                team_id=self.team.pk, deletion_type=DeletionType.Person, key=str(p.uuid)
            ).count()
            == 1
        )

    def test_ignores_duplicate_queueing(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        queue_person_event_deletion(self.team.pk, [p], actor=self.user)
        assert AsyncDeletion.objects.filter(team_id=self.team.pk).count() == 1


class DeletePersonsProfileTests(BaseTest):
    def test_deletes_persons_via_helpers(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
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
        p1 = create_person(team=self.team, distinct_ids=["a"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b"], properties={})
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

    def test_queue_delegates_to_start_recording_workflows(self):
        p1 = create_person(team=self.team, distinct_ids=["a"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b"], properties={})
        with patch("posthog.models.person.bulk_delete._start_recording_workflows") as start:
            queue_person_recording_deletion(self.team.pk, [p1, p2], actor=self.user)
            start.assert_called_once()
            (_, persons, _, _) = start.call_args.args
            assert {p.uuid for p in persons} == {p1.uuid, p2.uuid}

    @parameterized.expand(
        [
            ("single_batch_under_limit", 3, 100, 1),
            ("splits_across_batch_boundary", 3, 2, 2),
            ("one_workflow_per_full_batch", 5, 2, 3),
        ]
    )
    def test_batches_persons_into_workflows(self, _name, num_persons, batch_size, expected_workflows):
        # Guards the fan-out cap: one workflow per person previously saturated the
        # offline ClickHouse query pool. We must start ceil(persons / batch) workflows
        # while still covering every person's distinct IDs.
        persons = [_person_with_distinct_ids(f"did-{i}") for i in range(num_persons)]
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch("posthog.models.person.bulk_delete.sync_connect", return_value=client),
            patch("posthog.models.person.bulk_delete._RECORDING_DELETION_PERSONS_PER_WORKFLOW", batch_size),
        ):
            _start_recording_workflows(self.team.pk, persons, self.user, "test reason")

        assert client.start_workflow.call_count == expected_workflows
        started_distinct_ids = {
            distinct_id for call in client.start_workflow.call_args_list for distinct_id in call.args[1].distinct_ids
        }
        assert started_distinct_ids == {f"did-{i}" for i in range(num_persons)}
        assert all(call.args[0] == "delete-recordings-with-person" for call in client.start_workflow.call_args_list)

    def test_skips_batch_with_no_distinct_ids(self):
        person = _person_with_distinct_ids()
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with patch("posthog.models.person.bulk_delete.sync_connect", return_value=client):
            _start_recording_workflows(self.team.pk, [person], self.user, "test reason")
        client.start_workflow.assert_not_called()
