from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.cluster import ConnectionInfo, ExecutionDeadline, MutationWaiter, RetryPolicy, get_cluster
from posthog.models.person import Person
from posthog.models.person.bulk_delete import (
    PersonDeletionStep,
    delete_persons_profile,
    get_distinct_ids_for_membership_deletion,
)
from posthog.personhog_client.caller_tag import current_caller_tag, personhog_caller_tag
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import GetPersonsRequest
from posthog.temporal.delete_persons.delete_persons_workflow import (
    _delete_specific_persons_via_personhog,
    _delete_team_persons_batch_via_personhog,
)

from products.customer_analytics.backend.facade.membership_deletion import delete_person_membership


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def advance(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


class InlineExecutor:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def submit(self, fn: Callable[[], Any]) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn())
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs: Any) -> None:
        pass


class ClickHouse:
    def __init__(self, clock: Clock, mode: str = "done") -> None:
        self.clock = clock
        self.mode = mode
        self.connection = SimpleNamespace(socket=None, context=SimpleNamespace(server_info=object()))
        self.ids = {"first@example.com", "second@example.com"}
        self.staged_ids = set(self.ids)
        self.deletes: list[list[str]] = []
        self.capacity_probes = 0
        self.replica_probes = 0
        self.mutation = False
        self.network_settings: list[dict] = []

    def substitute_params(self, sql: str, params: dict, context: Any) -> str:
        return sql

    def execute(self, sql: str, params: dict | None = None, *, settings: dict | None = None) -> list[tuple]:
        self.network_settings.append(settings or {})
        params = params or {}
        if "clusterAllReplicas" in sql:
            return [("local", 9000, 1, 1, "online", "data")]
        if "startsWith(name" in sql:
            return [("membership_deletion_keys_retained",)]
        if "system.tables" in sql:
            return [(1,)]
        if "NOT is_done AND NOT is_killed" in sql:
            self.capacity_probes += 1
            return [(int(self.mode == "capacity"),)]
        if "countIf(is_done)" in sql:
            self.replica_probes += 1
            return [("mutation_1", self.mode != "replica")]
        if "system.mutations" in sql:
            return [("mutation_1" if self.mutation else None,)]
        is_staged = "membership_deletion_keys_" in sql
        ids = self.staged_ids if is_staged else self.ids
        if sql.startswith("DELETE FROM"):
            deleted = list(params.get("distinct_ids", ids))
            self.deletes.append(deleted)
            if self.mode == "fallback":
                self.clock.advance(6 if len(deleted) > 1 else 4)
                if len(deleted) > 1:
                    raise RuntimeError("batch failed")
            ids.difference_update(deleted)
            self.mutation = True
            return []
        if sql.startswith("SELECT 1"):
            return [(1,)] if ids else []
        if sql.startswith("SELECT count()"):
            return [(len(ids.intersection(params.get("distinct_ids", ids))),)]
        raise AssertionError(sql)


@contextmanager
def boundaries(clock: Clock, ch: ClickHouse) -> Iterator[None]:
    pool = SimpleNamespace(get_client=lambda: _client(ch))
    with ExitStack() as stack:
        stack.enter_context(patch("posthog.clickhouse.cluster.time.monotonic", side_effect=lambda: clock.now))
        stack.enter_context(patch("posthog.clickhouse.cluster.time.sleep", side_effect=clock.advance))
        stack.enter_context(patch("posthog.clickhouse.cluster.ThreadPoolExecutor", InlineExecutor))
        stack.enter_context(patch("posthog.clickhouse.cluster.default_client", return_value=ch))
        stack.enter_context(patch("posthog.clickhouse.cluster.ConnectionInfo.make_pool", return_value=pool))
        stack.enter_context(patch("posthog.models.person.util.publish_person_tombstone", return_value=[]))
        stack.enter_context(
            patch(
                "products.customer_analytics.backend.facade.membership_deletion.MEMBERSHIP_DELETION_SYNC_TIMEOUT_SECONDS",
                10,
            )
        )
        stack.enter_context(
            patch(
                "products.customer_analytics.backend.facade.membership_deletion.MEMBERSHIP_DELETION_BACKGROUND_TIMEOUT_SECONDS",
                10,
            )
        )
        yield


@contextmanager
def _client(ch: ClickHouse) -> Iterator[ClickHouse]:
    yield ch


@override_settings(CLICKHOUSE_AUX_CLUSTER="posthog", CLICKHOUSE_CLUSTER="posthog")
class TestMembershipDeletionAvailability(SimpleTestCase):
    @parameterized.expand([("capacity",), ("replica",), ("fallback",)])
    def test_expiry_keeps_profiles_and_retry_erases_live_and_retained_keys(self, mode: str) -> None:
        clock = Clock()
        ch = ClickHouse(clock, mode)
        persons = [
            Person(id=i + 1, team_id=1, uuid=uuid4(), created_at=datetime(2025, 1, 1, tzinfo=UTC)) for i in range(2)
        ]
        for person, did in zip(persons, sorted(ch.ids)):
            person._distinct_ids = [did]
        with fake_personhog_client() as fake, boundaries(clock, ch):
            for person in persons:
                fake.add_person(team_id=1, person_id=person.pk, uuid=str(person.uuid), distinct_ids=person.distinct_ids)
            result = delete_persons_profile(1, persons, actor=None, queue_ai_training_deletion=False)
            assert result.deleted_count == 0
            assert result.retryable_errors == [p.uuid for p in persons]
            assert {f.step for f in result.failures} == {PersonDeletionStep.DELETE_MEMBERSHIP}
            assert len(fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1, 2])).persons) == 2
            assert clock.now == 10
            assert ch.capacity_probes <= 2
            assert ch.replica_probes <= 1
            if mode == "fallback":
                assert [len(ids) for ids in ch.deletes] == [2, 1]
            ch.mode = "done"
            result = delete_persons_profile(1, persons, actor=None, queue_ai_training_deletion=False)
            assert result.deleted_count == 2
            assert result.failures == []
            assert not ch.ids
            assert not ch.staged_ids
            assert not fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1, 2])).persons
            assert all(0 < s["max_execution_time"] <= 10 for s in ch.network_settings)
            assert 0 < ch.connection.send_receive_timeout <= 10

    def test_bounded_identity_reads_preserve_the_sdk_caller_tag(self) -> None:
        tags: list[str] = []
        with fake_personhog_client() as fake, personhog_caller_tag("persons/deletion-distinct-ids"):
            fake.add_person(team_id=1, person_id=1, distinct_ids=["first@example.com"])
            read = fake.get_distinct_ids_for_person

            def tagged_read(request):
                tags.append(current_caller_tag())
                return read(request)

            with patch.object(fake, "get_distinct_ids_for_person", side_effect=tagged_read):
                ids = get_distinct_ids_for_membership_deletion(1, 1, ExecutionDeadline.after(3600))
            assert [d.id for d in ids] == ["first@example.com"]
            assert tags == ["persons/deletion-distinct-ids"]

    def test_identity_paging_stops_at_deadline_without_starting_membership_mutations(self) -> None:
        clock = Clock()
        ch = ClickHouse(clock)
        person = Person(id=1, team_id=1, uuid=uuid4())
        person._distinct_ids = ["first@example.com", "second@example.com", "third@example.com"]
        with fake_personhog_client() as fake, boundaries(clock, ch):
            fake.add_person(team_id=1, person_id=1, uuid=str(person.uuid), distinct_ids=person.distinct_ids)
            read = fake.get_distinct_ids_for_person

            def slow_page(request):
                clock.advance(min(6, 10 - clock.now))
                return read(request)

            with (
                patch("posthog.models.person.bulk_delete.QUEUED_DELETION_DISTINCT_ID_PAGE_SIZE", 1),
                patch.object(fake, "get_distinct_ids_for_person", side_effect=slow_page),
            ):
                result = delete_persons_profile(1, [person], actor=None, queue_ai_training_deletion=False)
            assert result.deleted_count == 0
            assert result.retryable_errors == [person.uuid]
            assert result.failures[0].step == PersonDeletionStep.DELETE_MEMBERSHIP
            assert len(fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1])).persons) == 1
            fake.assert_called("get_distinct_ids_for_person", times=2)
            assert clock.now == 10
            assert not ch.deletes

    @parameterized.expand([("by_ids", False), ("whole_team", True)])
    def test_temporal_expiry_keeps_identity_for_retry(self, _name: str, whole_team: bool) -> None:
        clock = Clock()
        ch = ClickHouse(clock, "capacity")
        with fake_personhog_client() as fake, boundaries(clock, ch):
            fake.add_person(team_id=1, person_id=1, uuid=str(uuid4()), distinct_ids=["first@example.com"])
            with self.assertRaises(TimeoutError):
                if whole_team:
                    _delete_team_persons_batch_via_personhog(1, 100)
                else:
                    _delete_specific_persons_via_personhog(1, [1])
            assert clock.now == 10
            assert len(fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1])).persons) == 1
            fake.assert_not_called("delete_persons")
            fake.assert_not_called("delete_persons_batch_for_team")

    @parameterized.expand([("bootstrap",), ("host",)])
    def test_network_timeout_cannot_resume_profile_deletion(self, boundary: str) -> None:
        clock = Clock()
        ch = ClickHouse(clock)
        pending: list[tuple[Callable[[], Any], Future[Any]]] = []
        submissions = 0

        class PendingFuture(Future[Any]):
            def result(self, timeout: float | None = None) -> Any:
                if not self.done():
                    assert timeout is not None
                    clock.advance(timeout)
                    raise TimeoutError("network timed out")
                return super().result(timeout)

        class DeferredExecutor(InlineExecutor):
            def submit(self, fn: Callable[[], Any]) -> Future[Any]:
                nonlocal submissions
                submissions += 1
                if boundary == "host" and submissions == 1:
                    return super().submit(fn)
                future = PendingFuture()
                pending.append((fn, future))
                return future

        def wait_for_pending(futures, *, timeout):
            clock.advance(timeout)
            return set(), set(futures)

        person = Person(id=1, team_id=1, uuid=uuid4())
        person._distinct_ids = ["first@example.com"]
        with fake_personhog_client() as fake, boundaries(clock, ch):
            fake.add_person(team_id=1, person_id=1, uuid=str(person.uuid), distinct_ids=person.distinct_ids)
            with (
                patch("posthog.clickhouse.cluster.ThreadPoolExecutor", DeferredExecutor),
                patch("posthog.clickhouse.cluster.wait", side_effect=wait_for_pending),
            ):
                result = delete_persons_profile(1, [person], actor=None, queue_ai_training_deletion=False)
            assert result.deleted_count == 0
            assert result.failures[0].step == PersonDeletionStep.DELETE_MEMBERSHIP
            assert clock.now == 10
            assert len(pending) == 1
            for fn, future in pending:
                with self.assertRaises(TimeoutError):
                    fn()
                future.set_exception(TimeoutError())
            assert len(fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1])).persons) == 1
            assert not ch.deletes

    def test_retry_delay_and_replica_poll_share_remaining_deadline(self) -> None:
        clock = Clock()
        ch = ClickHouse(clock, "replica")
        with boundaries(clock, ch):
            deadline = ExecutionDeadline.after(10)
            cluster = get_cluster(deadline=deadline)
            retry = RetryPolicy(max_attempts=3, delay=6, exceptions=(RuntimeError,))
            attempts = 0

            def failing_read(client: Client) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("retry")
                MutationWaiter("membership", {"mutation_1"}).wait(client, deadline=deadline)

            with self.assertRaises(TimeoutError):
                cluster.any_host(retry(failing_read, deadline=deadline)).result()
            assert attempts == 2
            assert clock.waits == [6, 4]
            assert ch.replica_probes == 1

    def test_failed_host_still_blocks_absence_inference_from_healthy_replica(self) -> None:
        clock = Clock()
        ch = ClickHouse(clock)
        ch.ids.clear()
        ch.staged_ids.clear()
        bootstrap = ClickHouse(clock)
        topology = [(host, 9000, 1, i + 1, "online", "data") for i, host in enumerate(["healthy", "sick"])]
        person = Person(id=1, team_id=1, uuid=uuid4())
        person._distinct_ids = ["first@example.com"]

        def make_pool(connection: ConnectionInfo, *args: Any, **kwargs: Any) -> SimpleNamespace:
            if connection.host == "sick":
                raise ConnectionError("host unavailable")
            return SimpleNamespace(get_client=lambda: _client(ch))

        with (
            fake_personhog_client() as fake,
            boundaries(clock, ch),
            patch.object(bootstrap, "execute", return_value=topology),
            patch("posthog.clickhouse.cluster.default_client", return_value=bootstrap),
            patch.object(ConnectionInfo, "make_pool", new=make_pool),
        ):
            fake.add_person(team_id=1, person_id=1, uuid=str(person.uuid), distinct_ids=person.distinct_ids)
            result = delete_persons_profile(1, [person], actor=None, queue_ai_training_deletion=False)
            assert result.deleted_count == 0
            assert result.retryable_errors == [person.uuid]
            assert {f.step for f in result.failures} == {PersonDeletionStep.DELETE_MEMBERSHIP}
            assert len(fake.get_persons(GetPersonsRequest(team_id=1, person_ids=[1])).persons) == 1
            assert not ch.deletes

    def test_empty_distinct_ids_do_not_start_discovery(self) -> None:
        with patch("posthog.clickhouse.cluster.default_client", side_effect=AssertionError("unexpected discovery")):
            delete_person_membership(1, [])
