import contextlib
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from confluent_kafka import KafkaError
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.kafka_client.client import ProduceResult
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
    resolve_persons_for_deletion,
    tombstone_and_publish_persons,
)
from posthog.models.person.util import (
    TOMBSTONE_DELIVERY_TIMEOUT_SECONDS,
    PersonTombstone,
    tombstone_persons_in_postgres,
)
from posthog.personhog_client.fake_client import get_active_fake
from posthog.personhog_client.proto import DeletePersonsMode
from posthog.test.persons import create_person


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _no_publish():
    # Keeps the Kafka produce out of the test; the fake personhog client still tombstones and acks.
    return patch("posthog.models.person.util.publish_person_tombstone", return_value=[])


def _rpc():
    return patch("posthog.models.person.bulk_delete.tombstone_persons_in_postgres", wraps=tombstone_persons_in_postgres)


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
    def test_tombstones_postgres_first_then_publishes_clickhouse_at_the_returned_versions_and_acks(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        fake = get_active_fake()
        acked_before = _sample("posthog_person_tombstone_acks_total", outcome="acked")
        with _no_publish() as publish:
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)

        assert result.deleted_count == 1
        assert result.errors == []
        request = next(call.request for call in reversed(fake.calls) if call.method == "delete_persons")
        assert request.mode == DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE
        publish.assert_called_once()
        tombstone = publish.call_args.args[1]
        # Exactly what the replica wrote: the fake bumps version 0 to 1 on both rows.
        assert (tombstone.uuid, tombstone.version) == (p.uuid, 1)
        assert [(d.id, d.version) for d in tombstone.distinct_ids] == [("a", 1)]
        assert publish.call_args.kwargs["created_at"] == p.created_at
        assert fake.tombstone_queue == {}
        assert _sample("posthog_person_tombstone_acks_total", outcome="acked") == acked_before + 1

    @parameterized.expand([("produce_raises",), ("delivery_fails",)])
    def test_counts_and_logs_a_person_whose_clickhouse_publish_failed_and_keeps_it_queued(self, case):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        undelivered = ProduceResult(topic="clickhouse_person")
        undelivered.set_result(KafkaError(-192, "Local: Message timed out"), None)
        publish = (
            patch("posthog.models.person.util.publish_person_tombstone", side_effect=RuntimeError("kafka down"))
            if case == "produce_raises"
            else patch("posthog.models.person.util.publish_person_tombstone", return_value=[undelivered])
        )
        with publish:
            result = delete_persons_profile(self.team.pk, [p], actor=self.user, organization_id=self.organization.id)

        # The Postgres tombstone is the deletion; the failed publish is reported on its own step.
        assert result.deleted_count == 1
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.PUBLISH_CLICKHOUSE_TOMBSTONE, p.uuid)
        ]
        assert ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", item_id=str(p.pk)).exists()
        assert list(get_active_fake().tombstone_queue) == [(self.team.pk, str(p.uuid))]

    @parameterized.expand([("delivered", True), ("timed_out", False)])
    def test_waits_once_for_kafka_delivery_before_acking(self, _name, delivered):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        pending = ProduceResult(topic="clickhouse_person")
        producer = MagicMock()
        if delivered:
            producer.flush.side_effect = lambda timeout: pending.set_result(None, None)
        waits_before = _sample("posthog_person_tombstone_delivery_wait_seconds_count", source="delete")
        with (
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[pending]),
            patch("posthog.models.person.util.get_producer", return_value=producer),
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user, organization_id=self.organization.id)

        # Both person topics resolve to this one producer, so it is flushed once, inside the delivery timeout.
        producer.flush.assert_called_once()
        assert 0 < producer.flush.call_args.args[0] <= TOMBSTONE_DELIVERY_TIMEOUT_SECONDS
        assert _sample("posthog_person_tombstone_delivery_wait_seconds_count", source="delete") == waits_before + 1
        assert result.deleted_count == 1
        if delivered:
            assert result.failures == []
            assert get_active_fake().tombstone_queue == {}
        else:
            assert [(f.step, f.person_uuid) for f in result.failures] == [
                (PersonDeletionStep.PUBLISH_CLICKHOUSE_TOMBSTONE, p.uuid)
            ]
            assert list(get_active_fake().tombstone_queue) == [(self.team.pk, str(p.uuid))]

    @parameterized.expand(
        [
            ("not_committed", False, False),
            ("committed_before_failing", True, False),
            ("committed_but_the_check_fails_too", True, True),
        ]
    )
    def test_a_failed_tombstone_rpc_counts_only_the_persons_it_did_not_commit(self, _name, committed, check_fails):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})

        def tombstone_then_fail(team_id, uuids, **_):
            if committed:
                tombstone_persons_in_postgres(team_id, uuids)
            raise RuntimeError("personhog down")

        check = (
            patch("posthog.models.person.bulk_delete.get_person_tombstones", side_effect=RuntimeError("still down"))
            if check_fails
            else contextlib.nullcontext()
        )
        with (
            patch("posthog.models.person.bulk_delete.tombstone_persons_in_postgres", side_effect=tombstone_then_fail),
            _no_publish() as publish,
            check,
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user, organization_id=self.organization.id)

        logged = ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", item_id=str(p.pk)).exists()
        if committed and not check_fails:
            assert result.deleted_count == 1
            assert result.failures == []
            assert publish.call_args.args[1].uuid == p.uuid
            assert logged
            return

        assert result.deleted_count == 0
        assert [(f.step, f.person_uuid) for f in result.failures] == [(PersonDeletionStep.TOMBSTONE_POSTGRES, p.uuid)]
        publish.assert_not_called()
        assert not logged
        if check_fails:
            # The error names the unknown state, and the queue row leaves the publish to the weekly sweep.
            assert result.failures[0].error.startswith("PersonTombstoneStateUnknown: RuntimeError: personhog down")
            assert list(get_active_fake().tombstone_queue) == [(self.team.pk, str(p.uuid))]

    @parameterized.expand(
        [
            # (name, budget, distinct IDs per person, persons per RPC call)
            ("each_over_budget_alone", 3, [2, 2, 2], [[0], [1], [2]]),
            ("exactly_at_budget_stays_together", 4, [2, 2, 2], [[0, 1], [2]]),
            ("wider_than_budget_goes_alone", 3, [1, 5, 1], [[0], [1], [2]]),
        ]
    )
    def test_splits_the_rpc_by_distinct_id_budget_and_waits_for_delivery_once(self, _name, budget, widths, expected):
        persons = [
            create_person(team=self.team, distinct_ids=[f"d{i}-{j}" for j in range(width)], properties={})
            for i, width in enumerate(widths)
        ]
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_IDS_PER_BATCH", budget),
            patch(
                "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
                wraps=tombstone_persons_in_postgres,
            ) as rpc,
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
        ):
            delete_persons_profile(self.team.pk, persons, actor=self.user)

        assert [call.args[1] for call in rpc.call_args_list] == [[persons[i].uuid for i in batch] for batch in expected]
        # However many RPC batches, one delivery wait and one ack for the whole request.
        acks = [call.request for call in get_active_fake().calls if call.method == "ack_person_tombstones"]
        assert [len(ack.tombstones) for ack in acks] == [len(persons)]

    def test_a_failed_queue_ack_is_only_logged(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        failed_before = _sample("posthog_person_tombstone_acks_total", outcome="ack_failed")
        with (
            patch("posthog.models.person.util.publish_person_tombstone", return_value=[]),
            patch("posthog.models.person.util.ack_person_tombstones", side_effect=RuntimeError("personhog down")),
        ):
            result = delete_persons_profile(self.team.pk, [p], actor=self.user)

        # The person is deleted and published; the row stays queued for the weekly sweep to clear.
        assert result.deleted_count == 1
        assert result.failures == []
        assert list(get_active_fake().tombstone_queue) == [(self.team.pk, str(p.uuid))]
        assert _sample("posthog_person_tombstone_acks_total", outcome="ack_failed") == failed_before + 1

    def test_reports_a_failed_activity_log_write_per_person_and_keeps_the_deletion(self):
        p1 = create_person(team=self.team, distinct_ids=["a"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b"], properties={})
        with (
            _no_publish(),
            patch(
                "posthog.models.person.bulk_delete.bulk_log_activity",
                side_effect=RuntimeError("activity log down"),
            ),
        ):
            result = delete_persons_profile(
                self.team.pk, [p1, p2], actor=self.user, organization_id=self.organization.id
            )
        assert result.deleted_count == 2
        assert [(f.step, f.person_uuid) for f in result.failures] == [
            (PersonDeletionStep.LOG_ACTIVITY, p1.uuid),
            (PersonDeletionStep.LOG_ACTIVITY, p2.uuid),
        ]
        assert result.errors == [p1.uuid, p2.uuid]
        assert get_active_fake().tombstone_queue == {}


class TombstoneAndPublishPersonsTests(BaseTest):
    def test_a_failed_clickhouse_publish_does_not_raise_and_stays_queued_for_the_sweep(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with patch("posthog.models.person.util.publish_person_tombstone", side_effect=RuntimeError("kafka down")):
            assert tombstone_and_publish_persons(self.team.pk, [p]) == 1

        assert list(get_active_fake().tombstone_queue) == [(self.team.pk, str(p.uuid))]


class ProcessQueuedPersonDeletionTests(BaseTest):
    def test_walks_every_page_of_distinct_ids_tombstones_at_exact_versions_and_logs_activity(self):
        p = create_person(team=self.team, distinct_ids=["a", "b", "c", "d", "e"], properties={})
        fake = get_active_fake()
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE", 2),
            _no_publish() as publish,
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
        assert fake is not None
        fake.assert_called("get_distinct_ids_for_person", times=3)
        request = next(call.request for call in reversed(fake.calls) if call.method == "delete_persons")
        assert request.mode == DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE
        assert sorted(d.id for d in publish.call_args.args[1].distinct_ids) == ["a", "b", "c", "d", "e"]
        assert fake.tombstone_queue == {}
        log = ActivityLog.objects.get(team_id=self.team.pk, scope="Person", item_id=str(p.pk))
        assert log.activity == "deleted"
        assert log.was_impersonated is True

    def test_does_not_log_a_deletion_twice_when_a_stale_read_resolves_the_person_again(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        # The fake hides a tombstoned person, so leave it live and report the tombstone from the patch.
        stale_tombstones = [PersonTombstone(uuid=p.uuid, version=1, distinct_ids=[])]
        with (
            patch("posthog.models.person.bulk_delete.tombstone_persons_in_postgres", return_value=stale_tombstones),
            _no_publish(),
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
        with _no_publish():
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

    def test_failed_postgres_tombstone_is_named_and_not_logged_as_deleted(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with patch(
            "posthog.models.person.bulk_delete.tombstone_persons_in_postgres",
            side_effect=RuntimeError("personhog down"),
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
        assert [(f.step, f.person_uuid) for f in result.failures] == [(PersonDeletionStep.TOMBSTONE_POSTGRES, p.uuid)]
        assert not ActivityLog.objects.filter(team_id=self.team.pk, scope="Person").exists()

    def test_skips_persons_that_no_longer_exist(self):
        with (
            _rpc() as rpc,
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
        rpc.assert_not_called()

    def test_failed_page_fetch_is_an_error_not_an_unbounded_fallback(self):
        p = create_person(team=self.team, distinct_ids=["a"], properties={})
        with (
            patch(
                "posthog.models.person.bulk_delete._paginated_get_distinct_ids_for_person",
                side_effect=RuntimeError("personhog down"),
            ),
            _rpc() as rpc,
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
        rpc.assert_not_called()

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
            _rpc() as rpc,
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
        rpc.assert_not_called()

    def test_runs_the_steps_per_batch_once_the_distinct_id_cap_is_reached(self):
        p1 = create_person(team=self.team, distinct_ids=["a1", "a2", "a3"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["b1", "b2", "b3"], properties={})
        p3 = create_person(team=self.team, distinct_ids=["c1"], properties={})
        with (
            patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_IDS_PER_BATCH", 4),
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion") as training,
            _rpc() as rpc,
            _no_publish(),
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
        assert sorted(u for call in rpc.call_args_list for u in call.args[1]) == sorted([p1.uuid, p2.uuid, p3.uuid])
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
            _rpc() as rpc,
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
        rpc.assert_not_called()

    def test_failed_training_deletion_for_one_person_does_not_block_the_others(self):
        p1 = create_person(team=self.team, distinct_ids=["bad"], properties={})
        p2 = create_person(team=self.team, distinct_ids=["good"], properties={})

        def training(_team_id, distinct_ids):
            if "bad" in distinct_ids:
                raise RuntimeError("session lookup timed out")

        with (
            patch("posthog.models.person.bulk_delete.queue_person_training_deletion", side_effect=training),
            _rpc() as rpc,
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
        assert rpc.call_args.args[1] == [p2.uuid]

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
            _rpc() as rpc,
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
        rpc.assert_not_called()


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
