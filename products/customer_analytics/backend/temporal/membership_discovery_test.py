import json
import logging
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from django.db import connection
from django.utils import timezone

from temporalio import activity
from temporalio.client import ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.redis import get_client as get_redis_client
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.membership import (
    MembershipCleanupBusy,
    MembershipExistence,
    MembershipKey,
    get_membership_cleanup_lease,
)
from products.customer_analytics.backend.logic.membership_discovery import (
    MembershipDiscoveryCounts,
    MembershipDiscoveryInput,
    MembershipDiscoveryStore,
    run_membership_discovery,
)
from products.customer_analytics.backend.models.membership_cleanup import MembershipCleanupCandidate
from products.customer_analytics.backend.temporal.membership_common import (
    BATCH_RETRY_ATTEMPTS,
    BATCH_RETRY_DELAY,
    HEARTBEAT_TIMEOUT,
)
from products.customer_analytics.backend.temporal.membership_discovery import (
    COORDINATOR_RUN_BUDGET,
    SCHEDULE_ID,
    TEAM_RUN_BUDGET,
    MembershipDiscoveryTeamWorkflow,
    MembershipDiscoveryWorkflow,
    create_membership_discovery_schedule,
    list_membership_discovery_teams_activity,
    membership_discovery_activity,
    record_membership_discovery_team_activity,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_more,elapsed,expected_batches,stop_reason",
    [
        (False, timedelta(), 1, "completed"),
        (True, timedelta(), 3, "batch_limit"),
        (True, TEAM_RUN_BUDGET, 1, "time_budget"),
    ],
)
async def test_team_workflow_stops_at_scan_or_run_limit(
    has_more: bool, elapsed: timedelta, expected_batches: int, stop_reason: str
) -> None:
    now = timezone.now()
    clock = now

    async def finish_batch(*args: object, **kwargs: object) -> MembershipDiscoveryCounts:
        nonlocal clock
        clock += elapsed
        return MembershipDiscoveryCounts(scanned=100, has_more=has_more)

    execute_activity = AsyncMock(side_effect=finish_batch)
    with (
        patch("products.customer_analytics.backend.temporal.membership_discovery.MAX_BATCHES_PER_TEAM", 3),
        patch("temporalio.workflow.now", side_effect=lambda: clock),
        patch("temporalio.workflow.logger") as run_logger,
        patch(
            "temporalio.workflow.info", return_value=SimpleNamespace(start_time=now, execution_timeout=TEAM_RUN_BUDGET)
        ),
        patch("temporalio.workflow.execute_activity", execute_activity),
    ):
        result = await MembershipDiscoveryTeamWorkflow().run(MembershipDiscoveryInput(team_id=1))
    assert result.scanned == 100 * expected_batches
    assert result.has_more == has_more
    summary = run_logger.info.call_args.kwargs["extra"]
    assert run_logger.info.call_args.args[0] == "membership_run_summary %s"
    assert json.loads(run_logger.info.call_args.args[1]) == summary
    assert summary["stop_reason"] == stop_reason
    assert summary["scanned"] == result.scanned
    assert summary["batches"] == expected_batches
    assert summary["duration_seconds"] == elapsed.total_seconds() * expected_batches


@pytest.mark.asyncio
async def test_coordinator_stops_between_teams_at_deadline() -> None:
    now = timezone.now()
    clock = now
    execute_activity = AsyncMock(side_effect=[[1, 2], None])

    async def finish_child(*args: object, **kwargs: object) -> MembershipDiscoveryCounts:
        nonlocal clock
        clock = now + COORDINATOR_RUN_BUDGET
        return MembershipDiscoveryCounts(scanned=100, discovered=2, has_more=True)

    execute_child = AsyncMock(side_effect=finish_child)
    with (
        patch("temporalio.workflow.now", side_effect=lambda: clock),
        patch("temporalio.workflow.logger") as run_logger,
        patch("temporalio.workflow.execute_activity", execute_activity),
        patch("temporalio.workflow.execute_child_workflow", execute_child),
    ):
        await MembershipDiscoveryWorkflow().run()
    assert execute_child.await_count == 1
    assert execute_child.call_args.args[1].team_id == 1
    assert execute_activity.call_args.args == (record_membership_discovery_team_activity, 1)
    assert execute_child.call_args.kwargs["execution_timeout"] <= TEAM_RUN_BUDGET
    summary = run_logger.info.call_args.kwargs["extra"]
    assert summary["scope"] == "coordinator"
    assert summary["stop_reason"] == "time_budget"
    assert summary["teams_completed"] == 1
    assert summary["scanned"] == 100
    assert summary["discovered"] == 2
    assert summary["duration_seconds"] == COORDINATOR_RUN_BUDGET.total_seconds()


@pytest.mark.django_db
def test_abandoned_lease_expires_before_activity_retry(team: Team) -> None:
    store = MembershipDiscoveryStore()

    def list_keys_with_bounded_lease(*args: object) -> list[MembershipKey]:
        ttl = get_redis_client().pttl(f"customer_analytics:membership_cleanup:{team.pk}")
        assert 0 < ttl <= BATCH_RETRY_DELAY.total_seconds() * 1000
        return []

    with patch.object(store, "list_keys", side_effect=list_keys_with_bounded_lease):
        assert run_membership_discovery(MembershipDiscoveryInput(team_id=team.pk), store).scanned == 0


@pytest.mark.django_db
def test_discovery_renews_lease_during_network_reads(team: Team) -> None:
    store = MembershipDiscoveryStore()
    lease = get_membership_cleanup_lease(team.pk)
    renewed = Event()
    extend = lease.extend

    def extend_and_signal(additional_time: float, replace_ttl: bool = False) -> bool:
        result = extend(additional_time, replace_ttl=replace_ttl)
        renewed.set()
        return result

    def list_keys_after_renewal(*args: object) -> list[MembershipKey]:
        assert renewed.wait(timeout=5)
        competing_lease = get_membership_cleanup_lease(team.pk)
        assert not competing_lease.acquire()
        return []

    with (
        patch("products.customer_analytics.backend.logic.membership.MEMBERSHIP_LEASE_RENEWAL_SECONDS", 0),
        patch(
            "products.customer_analytics.backend.logic.membership_discovery.get_membership_cleanup_lease",
            return_value=lease,
        ),
        patch.object(lease, "extend", side_effect=extend_and_signal),
        patch.object(store, "list_keys", side_effect=list_keys_after_renewal),
    ):
        assert run_membership_discovery(MembershipDiscoveryInput(team_id=team.pk), store).scanned == 0
    assert not get_redis_client().exists(lease.name)


@pytest.mark.django_db(transaction=True)
def test_discovery_lease_and_network_transaction_scope(team: Team) -> None:
    store = MembershipDiscoveryStore()
    lease = get_redis_client().lock(f"customer_analytics:membership_cleanup:{team.pk}", timeout=60)
    with lease, patch.object(store, "list_keys") as list_keys:
        with pytest.raises(MembershipCleanupBusy):
            run_membership_discovery(MembershipDiscoveryInput(team_id=team.pk), store)
        list_keys.assert_not_called()

    def list_keys_without_transaction(*args: object) -> list[MembershipKey]:
        assert not connection.in_atomic_block
        return [MembershipKey(group_type_index=0, group_key="test-account", distinct_id="test-person")]

    def lookup_without_transaction(*args: object, **kwargs: object) -> MembershipExistence:
        assert not connection.in_atomic_block
        return MembershipExistence(persons=frozenset(), groups=frozenset())

    with (
        patch.object(store, "list_keys", side_effect=list_keys_without_transaction),
        patch(
            "products.customer_analytics.backend.logic.membership_discovery.get_membership_existence",
            side_effect=lookup_without_transaction,
        ),
    ):
        assert run_membership_discovery(MembershipDiscoveryInput(team_id=team.pk), store).scanned == 1
    assert MembershipCleanupCandidate.objects.for_team(team.pk).count() == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("membership_cleanup_tables")
async def test_temporal_discovery_preserves_membership(
    team: Team, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_discovery.BATCH_SIZE", 1)
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_discovery.TEAM_BATCH_SIZE", 1)
    task_queue = str(uuid4())
    other_team_id = team.pk + 1000000

    def seed_membership() -> None:
        sync_execute(
            "INSERT INTO sharded_person_group_membership (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES",
            [
                (team_id, 0, "test-account", distinct_id, timezone.now(), timezone.now())
                for team_id, distinct_id in [
                    (team.pk, "first-person"),
                    (team.pk, "second-person"),
                    (other_team_id, "other-person"),
                ]
            ],
        )

    def assert_candidates() -> None:
        assert MembershipCleanupCandidate.objects.for_team(team.pk).count() == 4
        assert MembershipCleanupCandidate.objects.for_team(other_team_id).count() == 2
        assert sync_execute("SELECT count() FROM person_group_membership") == [(3,)]

    lost_result = False

    @activity.defn(name="membership_discovery_activity")
    async def retry_committed_batch(input: MembershipDiscoveryInput) -> MembershipDiscoveryCounts:
        nonlocal lost_result
        result = await membership_discovery_activity(input)
        if not lost_result:
            lost_result = True
            raise RuntimeError("Simulated lost activity result after checkpoint commit")
        return result

    await database_sync_to_async(seed_membership)()
    async with await WorkflowEnvironment.start_local() as environment:
        await create_membership_discovery_schedule(environment.client)
        description = await environment.client.get_schedule_handle(SCHEDULE_ID).describe()
        assert description.schedule.state.paused
        assert description.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        await create_membership_discovery_schedule(environment.client)
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[MembershipDiscoveryWorkflow, MembershipDiscoveryTeamWorkflow],
            activities=[
                list_membership_discovery_teams_activity,
                retry_committed_batch,
                record_membership_discovery_team_activity,
            ],
        ):
            await environment.client.execute_workflow(
                MembershipDiscoveryWorkflow.run,
                id=str(uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )
    await database_sync_to_async(assert_candidates)()
    assert lost_result
    summaries = [
        json.JSONDecoder().raw_decode(record.getMessage().removeprefix("membership_run_summary "))[0]
        for record in caplog.records
        if record.getMessage().startswith("membership_run_summary ")
    ]
    assert {summary["scope"] for summary in summaries} == {"team", "coordinator"}
    assert all(summary["job"] == "discovery" and summary["duration_seconds"] >= 0 for summary in summaries)
    assert any(summary.get("teams_completed", 0) > 0 for summary in summaries)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "execution_budget",
    [TEAM_RUN_BUDGET, timedelta(minutes=5), timedelta(minutes=5, microseconds=1), timedelta(minutes=5, microseconds=2)],
)
async def test_team_reserves_time_for_retries(execution_budget: timedelta) -> None:
    now = timezone.now()
    execute = AsyncMock(return_value=MembershipDiscoveryCounts())
    with (
        patch(
            "temporalio.workflow.info", return_value=SimpleNamespace(start_time=now, execution_timeout=execution_budget)
        ),
        patch("temporalio.workflow.now", return_value=now),
        patch("temporalio.workflow.execute_activity", execute),
        patch("temporalio.workflow.logger"),
    ):
        await MembershipDiscoveryTeamWorkflow().run(MembershipDiscoveryInput(team_id=1))
    options = execute.call_args.kwargs
    retry_time = options["start_to_close_timeout"] * BATCH_RETRY_ATTEMPTS + BATCH_RETRY_DELAY * (
        BATCH_RETRY_ATTEMPTS - 1
    )
    assert retry_time + HEARTBEAT_TIMEOUT <= execution_budget
    assert options["schedule_to_close_timeout"] == execution_budget


@pytest.mark.asyncio
async def test_team_failure_summary_retains_completed_batch_totals() -> None:
    now = timezone.now()
    with (
        patch(
            "temporalio.workflow.info", return_value=SimpleNamespace(start_time=now, execution_timeout=TEAM_RUN_BUDGET)
        ),
        patch("temporalio.workflow.now", return_value=now),
        patch("temporalio.workflow.logger") as run_logger,
        patch(
            "temporalio.workflow.execute_activity",
            side_effect=[MembershipDiscoveryCounts(scanned=100, has_more=True), RuntimeError("batch unavailable")],
        ),
    ):
        with pytest.raises(RuntimeError, match="batch unavailable"):
            await MembershipDiscoveryTeamWorkflow().run(MembershipDiscoveryInput(team_id=1))
    summary = run_logger.info.call_args.kwargs["extra"]
    assert summary["outcome"] == "failure"
    assert summary["stop_reason"] == "failure"
    assert summary["scanned"] == 100
    assert summary["batches"] == 1
