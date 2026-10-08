import asyncio
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import field, replace
from datetime import timedelta
from typing import TypeVar, cast
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from clickhouse_driver import Client
from clickhouse_driver.errors import ServerException
from parameterized import parameterized
from structlog.testing import capture_logs
from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster, ConnectionInfo, FuturesMap, HostInfo
from posthog.dataclasses import frozen
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.tombstone_log import list_pending_person_tombstones
from posthog.models.team import Team
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client

from products.customer_analytics.backend.logic.membership_deletion import stored_team_ids
from products.customer_analytics.backend.logic.membership_deletion_consumer import (
    CONSUMER,
    TeamScanOutcome,
    TombstonePageOutcome,
    TombstoneResume,
    process_tombstone_page,
    reconcile_deleted_teams,
)
from products.customer_analytics.backend.temporal import membership_deletion as worker
from products.customer_analytics.backend.temporal.membership_deletion import (
    MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME,
    MembershipDeletionCoordinatorInput,
    MembershipDeletionCoordinatorWorkflow,
    MembershipDeletionProgress,
    MembershipTeamScanInput,
    MembershipTombstonePageInput,
    progress_from_completion_result,
)

T = TypeVar("T")
DELETED_TEAM = 98765101
ABSENT_TEAM = 98765102
MEMBERSHIP = "sharded_person_group_membership"
CONFIG = "person_group_membership_config"
ALL_TABLES = frozenset({MEMBERSHIP, "person_group_membership", CONFIG, "distributed_person_group_membership_config"})
_HOST = HostInfo(ConnectionInfo("fake", None), 1, 1, None, None)


@frozen(frozen=False)
class _FakeClickHouse:
    tables: frozenset[str] = ALL_TABLES
    membership: list[tuple[int, int, str, str]] = field(default_factory=list)
    config: list[int] = field(default_factory=list)
    ignore_deletes: bool = False
    failing_teams: frozenset[int] = frozenset()
    failing_delete_number: int | None = None
    held_deletes: dict[int, threading.Event] = field(default_factory=dict)
    deletes: int = 0

    @staticmethod
    def _matches(team_id: int, distinct_id: str | None, parameters: Mapping[str, object]) -> bool:
        if "team_ids" in parameters:
            return team_id in cast(list[int], parameters["team_ids"])
        if "distinct_ids" not in parameters:
            return team_id == parameters["team_id"]
        return team_id == parameters["team_id"] and distinct_id in cast(list[str], parameters["distinct_ids"])

    def _delete(self, config: bool, parameters: Mapping[str, object]) -> None:
        self.deletes += 1
        teams = cast(list[int], parameters.get("team_ids", [parameters.get("team_id")]))
        if (release := self.held_deletes.get(self.deletes)) is not None:
            assert release.wait(timeout=10)
        if self.deletes == self.failing_delete_number or self.failing_teams & set(teams):
            raise ServerException(f"DB::Exception: cannot delete {parameters!r}", code=62)
        if self.ignore_deletes:
            return
        if config:
            self.config = [team for team in self.config if not self._matches(team, None, parameters)]
        else:
            self.membership = [row for row in self.membership if not self._matches(row[0], row[3], parameters)]

    def execute(
        self, sql: str, parameters: Mapping[str, object] | None = None, settings: Mapping[str, str] | None = None
    ) -> list[tuple[object, ...]]:
        parameters = parameters or {}
        if "system.tables" in sql:
            return [(int(parameters["name"] in self.tables),)]
        if "system.mutations" in sql:
            return [(0,)]
        config = CONFIG in sql
        if sql.startswith("DELETE"):
            self._delete(config, parameters)
            return []
        if sql.startswith("SELECT DISTINCT team_id"):
            stored = self.config if config else [row[0] for row in self.membership]
            after = cast(int, parameters["after"])
            teams: list[tuple[object, ...]] = [(team_id,) for team_id in sorted(set(stored)) if team_id > after]
            return teams[: cast(int, parameters["limit"])]
        if sql.startswith("SELECT 1") and "team_id" not in parameters:
            return [(1,)] if self.membership else []
        if sql.startswith("SELECT 1"):
            return [(1,)] if any(row[0] == parameters["team_id"] for row in self.membership) else []
        assert sql.startswith("SELECT count()") and "_row_exists = 1" in sql
        if config:
            return [(sum(self._matches(team, None, parameters) for team in self.config),)]
        return [(sum(self._matches(row[0], row[3], parameters) for row in self.membership),)]

    def remaining(self, team_id: int) -> list[str]:
        return sorted({row[3] for row in self.membership if row[0] == team_id})


class _FakeCluster:
    shard_role = NodeRole.DATA

    def __init__(self, clickhouse: _FakeClickHouse) -> None:
        self._client = cast(Client, clickhouse)

    @property
    def data_cluster_name(self) -> str:
        return settings.CLICKHOUSE_AUX_CLUSTER

    def any_host_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> "Future[T]":
        future: Future[T] = Future()
        try:
            future.set_result(fn(self._client))
        except Exception as error:
            future.set_exception(error)
        return future

    def map_hosts_by_role(self, fn: Callable[[Client], T], node_role: NodeRole) -> FuturesMap[HostInfo, T]:
        return FuturesMap({_HOST: self.any_host_by_role(fn, node_role)})

    def map_one_host_per_shard(self, fn: Callable[[Client], T]) -> FuturesMap[HostInfo, T]:
        return self.map_hosts_by_role(fn, NodeRole.DATA)


def _cluster(clickhouse: _FakeClickHouse) -> ClickhouseCluster:
    return cast(ClickhouseCluster, _FakeCluster(clickhouse))


def _membership(team_id: int, *distinct_ids: str) -> list[tuple[int, int, str, str]]:
    return [(team_id, 0, f"account-{index % 2}", value) for index, value in enumerate(distinct_ids)]


def _log(fake: FakePersonHogClient, team_id: int, *distinct_ids: str, person_uuid: str | None = None) -> int:
    return fake.add_tombstone_log_entry(
        team_id=team_id,
        person_uuid=person_uuid or str(uuid4()),
        person_version=3,
        distinct_ids=[(distinct_id, 2) for distinct_id in distinct_ids],
    )


def _budget(*, checks: int) -> Callable[[], bool]:
    remaining = iter(range(checks))
    return lambda: next(remaining, None) is None


def _pending() -> list[int]:
    return [entry.log_id for entry in list_pending_person_tombstones(CONSUMER, limit=1000).entries]


class TestMembershipTombstoneConsumer(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other")
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=DELETED_TEAM, key=str(DELETED_TEAM))

    def test_erases_unowned_ids_in_shared_chunks_and_acks_each_generation_by_log_id(self) -> None:
        large = [f"synthetic-{index:03}" for index in range(260)]
        clickhouse = _FakeClickHouse(
            membership=[
                *_membership(self.team.id, *large, "small-a", "small-b", "unrelated"),
                *_membership(self.other_team.id, "synthetic-000"),
            ]
        )
        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.id, person_id=7, uuid=str(uuid4()), distinct_ids=["synthetic-259"])
            person_uuid = str(uuid4())
            logged = [
                _log(fake, self.team.id, *large, person_uuid=person_uuid),
                _log(fake, self.team.id, "small-a", "small-b"),
            ]

            outcome = process_tombstone_page(_cluster(clickhouse), after=None)

            lookups = fake.assert_called("get_persons_by_distinct_ids_in_team")
            assert _pending() == []
            regenerated = _log(fake, self.team.id, *large, person_uuid=person_uuid)
            assert _pending() == [regenerated]

        assert outcome.acknowledged == len(logged) and outcome.failed_team_ids == () and outcome.next_cursor is None
        assert clickhouse.remaining(self.team.id) == ["synthetic-259", "unrelated"]
        assert clickhouse.remaining(self.other_team.id) == ["synthetic-000"]
        # 261 unowned IDs from two persons need two deletes, not one per person.
        assert clickhouse.deletes == 2
        assert all(len(call.request.distinct_ids) <= 250 for call in lookups)
        assert "properties" not in lookups[0].request.read_options.field_mask

    def test_a_long_generation_finishes_across_budgets_without_rereading_its_prefix(self) -> None:
        distinct_ids = [f"synthetic-{index:04}" for index in range(1000)]
        clickhouse = _FakeClickHouse(membership=_membership(self.team.id, *distinct_ids))
        with fake_personhog_client() as fake:
            log_id = _log(fake, self.team.id, *distinct_ids)
            outcomes = []
            resume = None
            for _ in range(5):
                outcome = process_tombstone_page(
                    _cluster(clickhouse), after=None, resume=resume, should_stop=_budget(checks=3)
                )
                outcomes.append(outcome)
                if outcome.resume is None:
                    break
                assert _pending() == [log_id]
                resume = outcome.resume

            payload_reads = [call.request.after_id for call in fake.assert_called("list_person_tombstone_distinct_ids")]
            looked_up = sum(
                len(call.request.distinct_ids) for call in fake.assert_called("get_persons_by_distinct_ids_in_team")
            )
            assert _pending() == []

        assert len(outcomes) == 2
        assert outcomes[0].resume is not None and outcomes[0].acknowledged == 0
        assert outcomes[1].acknowledged == 1
        assert payload_reads.count(0) == 1 and len(payload_reads) == 4
        assert looked_up == len(distinct_ids)
        assert clickhouse.remaining(self.team.id) == []

    def test_retries_continue_after_the_last_verified_chunk_even_when_an_attempt_dies_before_progress(self) -> None:
        distinct_ids = [f"synthetic-{index:03}" for index in range(600)]
        releases = {2: threading.Event(), 3: threading.Event()}
        clickhouse = _FakeClickHouse(membership=_membership(ABSENT_TEAM, *distinct_ids), held_deletes=releases)
        thread_finished = threading.Event()
        pool = worker.database_sync_to_async_pool

        def tracked_pool(fn: Callable[..., T]) -> Callable[..., object]:
            def run(*args: object) -> T:
                try:
                    return fn(*args)
                finally:
                    thread_finished.set()

            return pool(run)

        def dying_attempt(
            attempt: int, heartbeat_details: list[int], release: threading.Event, *, cancel_on_empty: bool
        ) -> list[tuple[int, ...]]:
            heartbeats: list[tuple[int, ...]] = []
            environment = ActivityEnvironment()
            environment.info = replace(
                ActivityEnvironment.default_info(),
                attempt=attempt,
                heartbeat_details=heartbeat_details,
                heartbeat_timeout=timedelta(seconds=1),
            )

            def on_heartbeat(*details: int) -> None:
                heartbeats.append(details)
                if details or cancel_on_empty:
                    environment.cancel()

            environment.on_heartbeat = on_heartbeat
            thread_finished.clear()
            # asyncio.run would wait for the abandoned thread, so a dying attempt gets a loop that does not.
            loop = asyncio.new_event_loop()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    loop.run_until_complete(
                        environment.run(
                            worker.membership_deletion_tombstone_page_activity, MembershipTombstonePageInput(after=None)
                        )
                    )
            finally:
                release.set()
                assert thread_finished.wait(timeout=10)
                loop.close()
            return heartbeats

        with (
            fake_personhog_client() as fake,
            patch.object(worker, "membership_cluster", return_value=_cluster(clickhouse)),
            patch.object(worker, "database_sync_to_async_pool", tracked_pool),
        ):
            log_id = _log(fake, ABSENT_TEAM, *distinct_ids)
            first = dying_attempt(1, [], releases[2], cancel_on_empty=False)
            # The second attempt dies at its first heartbeat, before it verifies anything new.
            second = dying_attempt(2, list(first[-1]), releases[3], cancel_on_empty=True)
            assert clickhouse.remaining(ABSENT_TEAM) == distinct_ids[500:]
            assert _pending() == [log_id]

            reads_before = len(fake.assert_called("list_person_tombstone_distinct_ids"))
            lookups_before = len(fake.assert_called("get_persons_by_distinct_ids_in_team"))
            third = ActivityEnvironment()
            third.info = replace(ActivityEnvironment.default_info(), attempt=3, heartbeat_details=list(second[-1]))
            outcome = asyncio.run(
                third.run(worker.membership_deletion_tombstone_page_activity, MembershipTombstonePageInput(after=None))
            )
            third_reads = [
                call.request.after_id
                for call in fake.assert_called("list_person_tombstone_distinct_ids")[reads_before:]
            ]
            third_lookups = {
                distinct_id
                for call in fake.assert_called("get_persons_by_distinct_ids_in_team")[lookups_before:]
                for distinct_id in call.request.distinct_ids
            }
            assert _pending() == []

        team_id, heartbeat_log_id, verified_after_id = first[-1]
        assert (team_id, heartbeat_log_id) == (ABSENT_TEAM, log_id)
        assert all(details == first[-1] for details in second)
        assert third_reads[0] == verified_after_id and 0 not in third_reads
        assert third_lookups.isdisjoint(distinct_ids[:250])
        assert set(distinct_ids[250:]) <= third_lookups
        assert outcome.acknowledged == 1 and outcome.resume is None
        assert clickhouse.remaining(ABSENT_TEAM) == []

    @parameterized.expand(
        [
            ("rows_survive", True, False, None, False),
            ("clickhouse_error", False, True, None, False),
            ("second_chunk_fails", False, False, 2, False),
            ("owner_lookup_fails", False, False, None, True),
        ]
    )
    def test_failed_erasure_keeps_the_generation_pending_and_logs_no_identifiers(
        self,
        _name: str,
        ignore_deletes: bool,
        team_fails: bool,
        failing_delete_number: int | None,
        lookup_fails: bool,
    ) -> None:
        secret = [f"secret-person-{index:03}@example.com" for index in range(260)]
        clickhouse = _FakeClickHouse(
            membership=_membership(self.team.id, *secret),
            ignore_deletes=ignore_deletes,
            failing_teams=frozenset({self.team.id}) if team_fails else frozenset(),
            failing_delete_number=failing_delete_number,
        )

        with fake_personhog_client() as fake, capture_logs() as logs:
            log_id = _log(fake, self.team.id, *secret)
            if lookup_fails:
                with patch.object(fake, "get_persons_by_distinct_ids_in_team", side_effect=RuntimeError(secret[0])):
                    outcome = process_tombstone_page(_cluster(clickhouse), after=None)
            else:
                outcome = process_tombstone_page(_cluster(clickhouse), after=None)
            assert _pending() == [log_id]

        assert outcome.acknowledged == 0 and outcome.failed_team_ids == (self.team.id,)
        assert "secret-person" not in repr(logs)

    def test_a_failing_team_does_not_hold_back_another_and_a_skipped_team_is_left_pending_untouched(self) -> None:
        clickhouse = _FakeClickHouse(
            membership=[*_membership(self.team.id, "a", "c"), *_membership(self.other_team.id, "b", "d")],
            failing_teams=frozenset({self.team.id}),
        )
        with fake_personhog_client() as fake:
            failing = [_log(fake, self.team.id, "a")]
            _log(fake, self.other_team.id, "b")

            first = process_tombstone_page(_cluster(clickhouse), after=None)

            assert _pending() == failing
            failing.append(_log(fake, self.team.id, "c"))
            _log(fake, self.other_team.id, "d")
            deletes, lookups = clickhouse.deletes, len(fake.assert_called("get_persons_by_distinct_ids_in_team"))

            second = process_tombstone_page(_cluster(clickhouse), after=None, skip_team_ids={self.team.id})

            assert _pending() == failing
            assert len(fake.assert_called("get_persons_by_distinct_ids_in_team")) == lookups + 1

        assert first.acknowledged == 1 and first.failed_team_ids == (self.team.id,)
        assert second.acknowledged == 1 and second.failed_team_ids == ()
        assert clickhouse.deletes == deletes + 1
        assert clickhouse.remaining(self.other_team.id) == []
        assert clickhouse.remaining(self.team.id) == ["a", "c"]

    def test_a_budget_stop_between_teams_on_the_first_page_keeps_the_pass_going_until_a_later_team(self) -> None:
        failing = [98765201, 98765202, 98765203]
        clickhouse = _FakeClickHouse(
            membership=[
                *(row for team_id in failing for row in _membership(team_id, "a")),
                *_membership(self.other_team.id, "b"),
            ],
            failing_teams=frozenset(failing),
        )
        with fake_personhog_client() as fake:
            failing_log_ids = [_log(fake, team_id, "a") for team_id in failing]
            _log(fake, self.other_team.id, "b")

            # Each team takes two budget checks, so the budget runs out before the third failing team starts.
            first = process_tombstone_page(_cluster(clickhouse), after=None, should_stop=_budget(checks=4))
            second = process_tombstone_page(
                _cluster(clickhouse), after=first.next_cursor, skip_team_ids=set(first.failed_team_ids)
            )

            assert _pending() == failing_log_ids

        assert (first.next_cursor, first.resume, first.acknowledged) == (0, None, 0)
        assert first.failed_team_ids == tuple(failing[:2])
        assert second.failed_team_ids == (failing[2],) and second.acknowledged == 1 and second.next_cursor is None
        assert clickhouse.remaining(self.other_team.id) == []

    @parameterized.expand([("tables_missing", frozenset()), ("team_has_no_rows", ALL_TABLES)])
    def test_acks_without_deleting_when_the_team_stores_no_membership(self, _name: str, tables: frozenset[str]) -> None:
        clickhouse = _FakeClickHouse(tables=tables, membership=_membership(self.other_team.id, "a"))
        with fake_personhog_client() as fake:
            _log(fake, self.team.id, "a")
            outcome = process_tombstone_page(_cluster(clickhouse), after=None)
            assert _pending() == []

        assert outcome.acknowledged == 1
        assert clickhouse.deletes == 0
        assert clickhouse.remaining(self.other_team.id) == ["a"]

    def test_unreachable_populated_storage_keeps_the_generation_pending(self) -> None:
        clickhouse = _FakeClickHouse(
            tables=frozenset({"person_group_membership"}), membership=_membership(self.team.id, "a")
        )
        with fake_personhog_client() as fake:
            log_id = _log(fake, self.team.id, "a")
            outcome = process_tombstone_page(_cluster(clickhouse), after=None)
            assert _pending() == [log_id]

        assert outcome.failed_team_ids == (self.team.id,)

    def test_confirmed_team_deletion_sweeps_the_team_and_an_unconfirmed_absent_team_is_erased_by_id(self) -> None:
        clickhouse = _FakeClickHouse(
            membership=[*_membership(DELETED_TEAM, "a", "b"), *_membership(ABSENT_TEAM, "a", "keep")],
            config=[DELETED_TEAM, ABSENT_TEAM],
        )
        with fake_personhog_client() as fake:
            _log(fake, DELETED_TEAM, "a")
            _log(fake, ABSENT_TEAM, "a")
            outcome = process_tombstone_page(_cluster(clickhouse), after=None)
            assert _pending() == []

        assert outcome.acknowledged == 2
        assert clickhouse.remaining(DELETED_TEAM) == []
        assert clickhouse.remaining(ABSENT_TEAM) == ["keep"]
        assert clickhouse.config == [ABSENT_TEAM]

    def test_team_scan_deletes_only_confirmed_deleted_teams_and_reports_unconfirmed_ones(self) -> None:
        failed_team = 98765103
        AsyncDeletion.objects.create(deletion_type=DeletionType.Team, team_id=failed_team, key=str(failed_team))
        clickhouse = _FakeClickHouse(
            membership=[
                *_membership(self.team.id, "live"),
                *_membership(DELETED_TEAM, "gone"),
                *_membership(ABSENT_TEAM, "unconfirmed"),
                *_membership(failed_team, "failing"),
            ],
            config=[self.team.id, DELETED_TEAM, ABSENT_TEAM],
            failing_teams=frozenset({failed_team}),
        )

        outcome = reconcile_deleted_teams(_cluster(clickhouse), after=0)

        assert (outcome.deleted_teams, outcome.unconfirmed_teams, outcome.failed_teams) == (1, 1, 1)
        assert outcome.next_cursor is None
        assert clickhouse.remaining(DELETED_TEAM) == []
        assert clickhouse.remaining(ABSENT_TEAM) == ["unconfirmed"]
        assert clickhouse.remaining(failed_team) == ["failing"]
        assert clickhouse.remaining(self.team.id) == ["live"]
        assert clickhouse.config == [self.team.id, ABSENT_TEAM]


class TestStoredTeamIds(SimpleTestCase):
    def test_pages_merge_membership_and_config_teams_without_skipping_any(self) -> None:
        clickhouse = _FakeClickHouse(
            membership=_membership(1, "a") + _membership(3, "a") + _membership(5, "a"), config=[2, 3, 6]
        )
        pages: list[list[int]] = []
        after: int | None = 0
        while after is not None:
            team_ids, after = stored_team_ids(_cluster(clickhouse), after=after, limit=2)
            pages.append(team_ids)

        assert pages == [[1, 2], [3, 5], [6]]


@frozen(frozen=False)
class _FakeCoordinatorLog:
    pending: dict[int, int]
    failing_team: int
    stored_deleted_teams: list[int]
    page_size: int = 2
    attempts: dict[int, int] = field(default_factory=dict)
    erased_teams: list[int] = field(default_factory=list)
    received: list[MembershipTombstonePageInput] = field(default_factory=list)
    failing_page_calls: frozenset[int] = frozenset()
    interrupted_first_page: TombstoneResume | None = None

    def tombstone_page(self, input: MembershipTombstonePageInput) -> TombstonePageOutcome:
        self.received.append(input)
        if len(self.received) == 1 and self.interrupted_first_page is not None:
            return TombstonePageOutcome(
                acknowledged=0, failed_team_ids=(), next_cursor=None, resume=self.interrupted_first_page
            )
        if len(self.received) in self.failing_page_calls:
            raise ApplicationError("personhog unavailable", non_retryable=True)
        log_ids = sorted(log_id for log_id in self.pending if input.after is None or log_id > input.after)
        page = log_ids[: self.page_size]
        failed: list[int] = []
        acknowledged = 0
        for team_id in dict.fromkeys(self.pending[log_id] for log_id in page):
            if team_id in input.skip_team_ids:
                continue
            self.attempts[team_id] = self.attempts.get(team_id, 0) + 1
            if team_id == self.failing_team:
                failed.append(team_id)
                continue
            for log_id in page:
                if self.pending[log_id] == team_id:
                    del self.pending[log_id]
                    acknowledged += 1
        return TombstonePageOutcome(
            acknowledged=acknowledged,
            failed_team_ids=tuple(failed),
            next_cursor=page[-1] if len(log_ids) > self.page_size else None,
        )

    def team_scan(self, input: MembershipTeamScanInput) -> TeamScanOutcome:
        stored = [team_id for team_id in self.stored_deleted_teams if team_id > input.after]
        if stored:
            self.stored_deleted_teams.remove(stored[0])
            self.erased_teams.append(stored[0])
        return TeamScanOutcome(
            deleted_teams=min(len(stored), 1),
            unconfirmed_teams=0,
            failed_teams=0,
            next_cursor=stored[0] if len(stored) > 1 else None,
        )


async def _run_coordinator_ticks(
    log: _FakeCoordinatorLog, ticks: int, progress: MembershipDeletionProgress | None = None
) -> list[MembershipDeletionProgress]:
    @activity.defn(name="membership_deletion_tombstone_page_activity")
    async def tombstone_page(input: MembershipTombstonePageInput) -> TombstonePageOutcome:
        return log.tombstone_page(input)

    @activity.defn(name="membership_deletion_team_scan_activity")
    async def team_scan(input: MembershipTeamScanInput) -> TeamScanOutcome:
        return log.team_scan(input)

    results: list[MembershipDeletionProgress] = []
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="membership-deletion-test",
            workflows=[MembershipDeletionCoordinatorWorkflow],
            activities=[tombstone_page, team_scan],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            for _ in range(ticks):
                # The schedule hands each run the last result. A direct start passes it as input instead.
                progress = await environment.client.execute_workflow(
                    MEMBERSHIP_DELETION_COORDINATOR_WORKFLOW_NAME,
                    MembershipDeletionCoordinatorInput(progress=progress or MembershipDeletionProgress()),
                    id=f"membership-deletion-test-{uuid4()}",
                    task_queue="membership-deletion-test",
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    result_type=MembershipDeletionProgress,
                )
                results.append(progress)
    return results


@pytest.mark.asyncio
async def test_coordinator_carries_an_open_generation_to_the_next_page_and_returns_it_for_the_next_tick() -> None:
    resume = TombstoneResume(team_id=1, log_id=7, after_id=250)
    log = _FakeCoordinatorLog(
        pending={},
        failing_team=0,
        stored_deleted_teams=[],
        failing_page_calls=frozenset({2}),
        interrupted_first_page=resume,
    )

    [result] = await _run_coordinator_ticks(log, ticks=1)

    assert [input.resume for input in log.received] == [None, resume]
    assert result.resume == resume


@pytest.mark.asyncio
async def test_a_failing_oldest_team_does_not_starve_later_teams_or_the_deleted_team_scan_across_runs() -> None:
    failing_team, healthy_team = 1, 2
    log = _FakeCoordinatorLog(
        pending={**dict.fromkeys(range(1, 7), failing_team), 7: healthy_team, 8: healthy_team},
        failing_team=failing_team,
        stored_deleted_teams=[101, 102, 103],
    )

    with patch.object(worker, "MAX_TOMBSTONE_PAGES_PER_RUN", 2):
        first, second, third = await _run_coordinator_ticks(log, ticks=3)

    assert first == MembershipDeletionProgress(tombstone_after=4, team_after=101, skipped_team_ids=(failing_team,))
    assert second == MembershipDeletionProgress()
    assert log.erased_teams == [101, 102, 103]
    assert sorted(log.pending) == [1, 2, 3, 4, 5, 6]
    # The failing team is tried once per pass: in run 1, then again when run 3 starts a new pass.
    assert log.attempts == {failing_team: 2, healthy_team: 1}
    assert third.skipped_team_ids == (failing_team,)


class TestCompletionResult(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_result", None, MembershipDeletionProgress()),
            (
                "older_resume_result",
                {"team_id": 1, "log_id": 7, "after_id": 250},
                MembershipDeletionProgress(resume=TombstoneResume(team_id=1, log_id=7, after_id=250)),
            ),
            (
                "current_result",
                {
                    "tombstone_after": 40,
                    "resume": {"team_id": 1, "log_id": 41, "after_id": 250},
                    "team_after": 9,
                    "skipped_team_ids": [3, 4],
                },
                MembershipDeletionProgress(
                    tombstone_after=40,
                    resume=TombstoneResume(team_id=1, log_id=41, after_id=250),
                    team_after=9,
                    skipped_team_ids=(3, 4),
                ),
            ),
            ("malformed_result", {"tombstone_after": "not-a-cursor"}, MembershipDeletionProgress()),
        ]
    )
    def test_reads_every_result_shape_without_failing_the_run(
        self, _name: str, value: object, expected: MembershipDeletionProgress
    ) -> None:
        assert progress_from_completion_result(value) == expected
