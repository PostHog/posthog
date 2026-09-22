from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person import Person
from posthog.models.person.bulk_delete import (
    PersonDeletionStep,
    _start_recording_workflows,
    delete_persons_profile,
    process_queued_person_deletion,
    queue_person_event_deletion,
    queue_person_recording_deletion,
    republish_tombstones,
    resolve_persons_for_deletion,
)
from posthog.models.person.util import DistinctIdForPerson, PersonTombstone, PersonTombstones
from posthog.personhog_client.fake_client import get_active_fake
from posthog.personhog_client.proto import DeletePersonsMode
from posthog.test.persons import create_person


def _person_with_distinct_ids(*distinct_ids: str) -> Person:
    # Unsaved Person with distinct_ids cached, so reads stay in-memory in the async fan-out.
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

    def test_without_distinct_ids_keeps_only_the_requested_ids_that_matched(self):
        p = create_person(team=self.team, distinct_ids=["a", "b", "c"], properties={})
        [resolved] = resolve_persons_for_deletion(
            self.team.pk, uuids=None, distinct_ids=["a", "b", "ghost"], with_distinct_ids=False
        )
        assert resolved.uuid == p.uuid
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
        ch_delete.assert_called_once()
        assert ch_delete.call_args.kwargs["person"] == p
        assert [d.id for d in ch_delete.call_args.kwargs["distinct_ids"]] == ["a"]
        pg_delete.assert_called_once_with(self.team.pk, [p])

    @parameterized.expand(
        [
            ("batch_fetch_fails", {"side_effect": RuntimeError("personhog down")}),
            ("person_missing_from_batch", {"return_value": {}}),
        ]
    )
    def test_falls_back_to_per_person_lookup(self, _name, batch_behavior):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch("posthog.models.person.bulk_delete._batched_get_distinct_ids_for_persons", **batch_behavior),
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)
        assert result.deleted_count == 1
        assert result.errors == []
        assert ch_delete.call_args.kwargs["distinct_ids"] is None
        pg_delete.assert_called_once_with(self.team.pk, [p])

    def test_reports_a_failed_postgres_delete_per_person_instead_of_raising(self):
        p1 = create_person(team=self.team, distinct_ids=["a"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch(
                "posthog.models.person.bulk_delete.delete_persons_from_postgres",
                side_effect=RuntimeError("personhog down"),
            ),
        ):
            result = delete_persons_profile(
                self.team.pk, [p1, p2], actor=self.user, organization_id=self.organization.id
            )
        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.DELETE_POSTGRES, p1.uuid),
            (PersonDeletionStep.DELETE_POSTGRES, p2.uuid),
        ]
        assert result.errors == [p1.uuid, p2.uuid]
        assert not ActivityLog.objects.filter(team_id=self.team.pk, scope="Person").exists()

    def test_reports_a_failed_activity_log_write_per_person_and_keeps_the_deletion(self):
        p1 = create_person(team=self.team, distinct_ids=["a"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
            patch(
                "posthog.models.person.bulk_delete.bulk_log_activity",
                side_effect=RuntimeError("activity log down"),
            ),
        ):
            result = delete_persons_profile(
                self.team.pk, [p1, p2], actor=self.user, organization_id=self.organization.id
            )
        pg_delete.assert_called_once_with(self.team.pk, [p1, p2])
        assert result.deleted_count == 2
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.LOG_ACTIVITY, p1.uuid),
            (PersonDeletionStep.LOG_ACTIVITY, p2.uuid),
        ]
        assert result.errors == [p1.uuid, p2.uuid]

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


@override_settings(PERSON_DELETE_TOMBSTONE=True)
class TombstoneDeletePersonsProfileTests(BaseTest):
    def test_tombstones_postgres_first_then_publishes_clickhouse_at_the_returned_versions(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        fake = get_active_fake()
        assert fake is not None
        with (
            patch("posthog.models.person.bulk_delete.delete_person") as legacy_ch_delete,
            patch("posthog.models.person.bulk_delete.publish_person_tombstone") as publish,
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)

        assert result.deleted_count == 1
        assert result.errors == []
        legacy_ch_delete.assert_not_called()
        request = next(call.request for call in reversed(fake.calls) if call.method == "delete_persons")
        assert request.mode == DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE
        publish.assert_called_once()
        tombstone = publish.call_args.args[1]
        # Exactly what the replica wrote: the fake bumps version 0 to 1 on both rows.
        assert (tombstone.uuid, tombstone.version) == (p.uuid, 1)
        assert [(d.id, d.version) for d in tombstone.distinct_ids] == [("a", 1)]
        assert publish.call_args.kwargs["created_at"] == p.created_at

    def test_counts_and_logs_a_person_whose_clickhouse_publish_failed(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with patch(
            "posthog.models.person.bulk_delete.publish_person_tombstone", side_effect=RuntimeError("kafka down")
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user, organization_id=self.organization.id)

        # The Postgres tombstone is the deletion; the failed publish is reported on its own step.
        assert result.deleted_count == 1
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.PUBLISH_CLICKHOUSE_TOMBSTONE, p.uuid)
        ]
        assert ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", item_id=str(p.pk)).exists()

    def test_reports_a_failed_tombstone_rpc_against_the_postgres_step(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch(
                "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
                side_effect=RuntimeError("personhog down"),
            ),
            patch("posthog.models.person.bulk_delete.publish_person_tombstone") as publish,
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)

        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [(PersonDeletionStep.TOMBSTONE_POSTGRES, p.uuid)]
        publish.assert_not_called()

    def test_splits_the_rpc_by_distinct_id_budget(self):
        persons = [create_person(team=self.team, distinct_ids=[f"d{i}a", f"d{i}b"], properties={}) for i in range(3)]
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_IDS_PER_BATCH", 3),
            # Sizing reads the distinct IDs the resolve loaded, so a failed fetch cannot shrink a person to one.
            patch(
                "posthog.models.person.bulk_delete._batched_get_distinct_ids_for_persons",
                side_effect=RuntimeError("personhog down"),
            ),
            patch(
                "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
                return_value=PersonTombstones(tombstones=[], newly_tombstoned=0),
            ) as rpc,
            patch("posthog.models.person.bulk_delete.publish_person_tombstone"),
        ):
            delete_persons_profile(self.team.pk, persons, actor=self.user)

        assert [call.args[1] for call in rpc.call_args_list] == [[p.uuid] for p in persons]


class ProcessQueuedPersonDeletionTests(BaseTest):
    def test_walks_every_page_of_distinct_ids_and_logs_activity(self):
        p = create_person(team=self.team, distinct_ids=["a", "b", "c", "d", "e"], properties={})
        fake = get_active_fake()
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE", 2),
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=True,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 1
        assert result.errors == []
        assert sorted(d.id for d in ch_delete.call_args.kwargs["distinct_ids"]) == ["a", "b", "c", "d", "e"]
        assert fake is not None
        fake.assert_called("get_distinct_ids_for_person", times=3)
        pg_delete.assert_called_once()
        assert [person.uuid for person in pg_delete.call_args.args[1]] == [p.uuid]
        log = ActivityLog.objects.get(team_id=self.team.pk, scope="Person", item_id=str(p.pk))
        assert log.activity == "deleted"
        assert log.was_impersonated is True

    def test_does_not_log_a_deletion_twice_when_a_stale_read_resolves_the_person_again(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres"),
        ):
            for _attempt in range(2):
                process_queued_person_deletion(
                    self.team.pk,
                    [str(p.uuid)],
                    delete_profile=True,
                    delete_recordings=False,
                    actor=self.user,
                    was_impersonated=False,
                    organization_id=self.organization.id,
                )
        assert ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", item_id=str(p.pk)).count() == 1

    def test_logs_deletion_without_a_user_when_the_actor_is_gone(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres"),
        ):
            process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=None,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        log = ActivityLog.objects.get(team_id=self.team.pk, scope="Person", item_id=str(p.pk))
        assert log.user is None

    def test_failed_postgres_delete_is_named_and_not_logged_as_deleted(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch(
                "posthog.models.person.bulk_delete.delete_persons_from_postgres",
                side_effect=RuntimeError("personhog down"),
            ),
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [(PersonDeletionStep.DELETE_POSTGRES, p.uuid)]
        assert not ActivityLog.objects.filter(team_id=self.team.pk, scope="Person").exists()

    def test_skips_persons_that_no_longer_exist(self):
        with (
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(uuid4())],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 0
        assert result.errors == []
        ch_delete.assert_not_called()
        pg_delete.assert_not_called()

    def test_failed_page_fetch_is_an_error_not_an_unbounded_fallback(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch(
                "posthog.models.person.bulk_delete._paginated_get_distinct_ids_for_person",
                side_effect=RuntimeError("personhog down"),
            ),
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [(PersonDeletionStep.FETCH_DISTINCT_IDS, p.uuid)]
        assert "RuntimeError: personhog down" in result.failures[0].error
        ch_delete.assert_not_called()
        pg_delete.assert_not_called()

    def test_unmatched_distinct_ids_queue_training_deletion_and_fail_without_a_person(self):
        with patch(
            "posthog.models.person.bulk_delete.queue_person_training_deletion", side_effect=RuntimeError("down")
        ) as training:
            result = process_queued_person_deletion(
                self.team.pk,
                [],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
                unmatched_distinct_ids=["ghost"],
            )
        training.assert_called_once_with(self.team.pk, ["ghost"])
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.QUEUE_TRAINING_DELETION, None)
        ]

    def test_resolve_failure_is_recorded_for_every_requested_person(self):
        uuids = [uuid4(), uuid4()]
        with patch(
            "posthog.models.person.bulk_delete._fetch_persons_by_uuids_via_personhog",
            side_effect=RuntimeError("personhog down"),
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(u) for u in uuids],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.RESOLVE_PERSONS, u) for u in uuids
        ]

    @parameterized.expand(
        [
            ("training", "queue_person_training_deletion", PersonDeletionStep.QUEUE_TRAINING_DELETION),
            ("recordings", "_start_recording_workflows", PersonDeletionStep.QUEUE_RECORDING_DELETION),
        ]
    )
    def test_failed_prerequisite_step_is_named_and_blocks_the_profile_delete(self, _name, target, step):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        patches = {
            "queue_person_training_deletion": patch("posthog.models.person.bulk_delete.queue_person_training_deletion"),
            "_start_recording_workflows": patch("posthog.models.person.bulk_delete._start_recording_workflows"),
        }
        patches[target] = patch(f"posthog.models.person.bulk_delete.{target}", side_effect=RuntimeError("down"))
        with (
            patches["queue_person_training_deletion"],
            patches["_start_recording_workflows"],
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=True,
                delete_recordings=True,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [(step, p.uuid)]
        ch_delete.assert_not_called()
        pg_delete.assert_not_called()

    def test_runs_the_steps_per_batch_once_the_distinct_id_cap_is_reached(self):
        p1 = create_person(team=self.team, distinct_ids=["a1", "a2", "a3"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b1", "b2", "b3"], properties={})
        p3 = create_person(team=self.team, distinct_ids=["c1"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_IDS_PER_BATCH", 4),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion") as training,
            patch("posthog.models.person.bulk_delete.delete_person"),
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p1.uuid), str(p2.uuid), str(p3.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 3
        assert result.failures == []
        # p1 and p2 fill the cap together; p3 runs in a second, smaller batch. Training deletion is one call per batch.
        assert [[person.uuid for person in call.args[1]] for call in pg_delete.call_args_list] == [
            [p1.uuid, p2.uuid],
            [p3.uuid],
        ]
        assert [sorted(call.args[1]) for call in training.call_args_list] == [
            ["a1", "a2", "a3", "b1", "b2", "b3"],
            ["c1"],
        ]

    def test_releases_each_batch_of_distinct_id_strings_after_its_steps_run(self):
        p1 = create_person(team=self.team, distinct_ids=["a1", "a2"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b1"], properties={})
        seen: list[Person] = []

        def capture(_team_id, persons, *_args, **_kwargs):
            seen.extend(persons)
            return 0

        with patch("posthog.models.person.bulk_delete._run_queued_deletion_steps", side_effect=capture):
            process_queued_person_deletion(
                self.team.pk,
                [str(p1.uuid), str(p2.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert {person.uuid for person in seen} == {p1.uuid, p2.uuid}
        assert all(person._distinct_ids is None for person in seen)

    def test_stops_isolating_training_failures_after_repeated_failures(self):
        persons = [create_person(team=self.team, distinct_ids=[f"d{i}"], properties={}) for i in range(5)]
        with (
            patch(
                "posthog.models.person.bulk_delete.queue_person_training_deletion", side_effect=RuntimeError("down")
            ) as training,
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid) for p in persons],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        # One flattened call, then per-person calls until the breaker trips; nobody is deleted.
        assert training.call_count == 1 + 3
        assert {f.person_uuid for f in result.failures} == {p.uuid for p in persons}
        assert {f.step for f in result.failures} == {PersonDeletionStep.QUEUE_TRAINING_DELETION}
        ch_delete.assert_not_called()
        pg_delete.assert_not_called()

    def test_failed_training_deletion_for_one_person_does_not_block_the_others(self):
        p1 = create_person(team=self.team, distinct_ids=["bad"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["good"], properties={})

        def training(_team_id, distinct_ids):
            if "bad" in distinct_ids:
                raise RuntimeError("session lookup timed out")

        with (
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion", side_effect=training),
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p1.uuid), str(p2.uuid)],
                delete_profile=True,
                delete_recordings=False,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 1
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.QUEUE_TRAINING_DELETION, p1.uuid)
        ]
        assert ch_delete.call_args.kwargs["person"].uuid == p2.uuid
        assert [person.uuid for person in pg_delete.call_args.args[1]] == [p2.uuid]

    def test_recordings_only_pages_distinct_ids_into_workflows_without_deleting(self):
        p = create_person(team=self.team, distinct_ids=["a", "b", "c"], properties={})
        # Snapshot at call time: the processor releases each person's IDs once its batch has run.
        started: list[list[str]] = []
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE", 2),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion") as training,
            patch(
                "posthog.models.person.bulk_delete._start_recording_workflows",
                side_effect=lambda _t, persons, *_a: started.extend(sorted(p.distinct_ids) for p in persons),
            ),
            patch("posthog.models.person.bulk_delete.delete_person") as ch_delete,
            patch("posthog.models.person.bulk_delete.delete_persons_from_postgres") as pg_delete,
        ):
            result = process_queued_person_deletion(
                self.team.pk,
                [str(p.uuid)],
                delete_profile=False,
                delete_recordings=True,
                actor=self.user,
                was_impersonated=False,
                organization_id=self.organization.id,
            )
        assert result.deleted_count == 0
        assert result.errors == []
        assert sorted(training.call_args.args[1]) == ["a", "b", "c"]
        assert started == [["a", "b", "c"]]
        ch_delete.assert_not_called()
        pg_delete.assert_not_called()


@override_settings(PERSON_DELETE_TOMBSTONE=True)
class RepublishUnresolvedTombstonesTests(BaseTest):
    def _run(self, person_uuid):
        return process_queued_person_deletion(
            self.team.pk,
            [str(person_uuid)],
            delete_profile=True,
            delete_recordings=False,
            actor=None,
            was_impersonated=False,
            organization_id=None,
        )

    def test_republishes_tombstones_for_a_person_that_no_longer_resolves(self):
        gone = uuid4()
        tombstone = PersonTombstone(uuid=gone, version=7, distinct_ids=[DistinctIdForPerson(id="x", version=3)])
        with (
            patch(
                "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
                return_value=PersonTombstones(tombstones=[tombstone], newly_tombstoned=0),
            ) as rpc,
            patch("posthog.models.person.bulk_delete.publish_person_tombstone") as publish,
        ):
            result = self._run(gone)

        assert result.errors == []
        assert result.deleted_count == 0
        rpc.assert_called_once_with(self.team.pk, [gone])
        publish.assert_called_once_with(self.team.pk, tombstone)

    def test_counts_a_live_person_that_the_republish_tombstoned(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        before = REGISTRY.get_sample_value("posthog_person_deletion_republish_tombstoned_live_total") or 0.0
        with (
            # A lagging read that misses a live person.
            patch("posthog.models.person.bulk_delete._fetch_persons_by_uuids_via_personhog", return_value=[]),
            patch("posthog.models.person.bulk_delete.publish_person_tombstone") as publish,
        ):
            self._run(p.uuid)

        after = REGISTRY.get_sample_value("posthog_person_deletion_republish_tombstoned_live_total") or 0.0
        assert after - before == 1
        assert publish.call_args.args[1].uuid == p.uuid

    def test_republish_calls_the_rpc_per_chunk_and_isolates_a_failed_chunk(self):
        uuids = [uuid4() for _ in range(3)]

        def rpc(_team_id, chunk):
            if chunk == uuids[2:]:
                raise RuntimeError("deadline exceeded")
            return PersonTombstones(
                tombstones=[PersonTombstone(uuid=u, version=1, distinct_ids=[]) for u in chunk], newly_tombstoned=0
            )

        with (
            patch("posthog.models.person.bulk_delete.REPUBLISH_UUIDS_PER_CALL", 2),
            patch("posthog.models.person.bulk_delete.tombstone_persons_in_postgres", side_effect=rpc) as call,
            patch("posthog.models.person.bulk_delete.publish_person_tombstone"),
        ):
            assert republish_tombstones(self.team.pk, uuids) == [uuids[2]]
        assert [c.args[1] for c in call.call_args_list] == [uuids[:2], uuids[2:]]

    def test_does_not_republish_after_a_failed_resolve(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch(
                "posthog.models.person.bulk_delete._fetch_persons_by_uuids_via_personhog",
                side_effect=RuntimeError("personhog down"),
            ),
            patch("posthog.models.person.bulk_delete.tombstone_persons_in_postgres") as rpc,
        ):
            result = self._run(p.uuid)

        # A live person that merely failed to resolve must not be tombstoned behind its other steps.
        assert [f.step for f in result.failures] == [PersonDeletionStep.RESOLVE_PERSONS]
        rpc.assert_not_called()

    @parameterized.expand(
        [
            ("tombstone_call_fails", True, None, [0, 1]),
            ("one_publish_fails", False, 0, [0]),
            ("all_published", False, None, []),
        ]
    )
    def test_republish_returns_the_uuids_still_unpublished(self, _name, rpc_fails, failing_publish, expected):
        uuids = [uuid4(), uuid4()]
        tombstones = [PersonTombstone(uuid=u, version=7, distinct_ids=[]) for u in uuids]

        def publish(_team_id, tombstone):
            if failing_publish is not None and tombstone.uuid == uuids[failing_publish]:
                raise RuntimeError("kafka down")

        with (
            patch(
                "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
                side_effect=RuntimeError("deadline exceeded") if rpc_fails else None,
                return_value=PersonTombstones(tombstones=tombstones, newly_tombstoned=0),
            ),
            patch("posthog.models.person.bulk_delete.publish_person_tombstone", side_effect=publish),
        ):
            assert republish_tombstones(self.team.pk, uuids) == [uuids[i] for i in expected]


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

    @parameterized.expand(
        [
            ("packs_until_distinct_id_cap", [2, 2, 2], 4, 2),
            ("single_person_over_cap_is_split", [5, 1], 4, 3),
            ("wide_person_splits_into_capped_workflows", [9], 4, 3),
            ("every_distinct_id_own_workflow_when_cap_tiny", [2, 2], 1, 4),
        ]
    )
    def test_chunks_by_distinct_id_count(self, _name, distinct_id_counts, cap, expected_workflows):
        persons = [
            _person_with_distinct_ids(*[f"p{i}-d{j}" for j in range(count)])
            for i, count in enumerate(distinct_id_counts)
        ]
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with (
            patch("posthog.models.person.bulk_delete.sync_connect", return_value=client),
            patch("posthog.models.person.bulk_delete._MAX_DISTINCT_IDS_PER_WORKFLOW", cap),
        ):
            _start_recording_workflows(self.team.pk, persons, self.user, "test reason")
        assert client.start_workflow.call_count == expected_workflows

    def test_uses_empty_deleted_by_when_actor_missing(self):
        client = MagicMock()
        client.start_workflow = AsyncMock()
        with patch("posthog.models.person.bulk_delete.sync_connect", return_value=client):
            _start_recording_workflows(self.team.pk, [_person_with_distinct_ids("a")], None, "test reason")
        client.start_workflow.assert_called_once()
        assert client.start_workflow.call_args.args[1].config.deleted_by == ""
