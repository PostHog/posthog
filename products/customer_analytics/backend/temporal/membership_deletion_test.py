import logging
from datetime import timedelta
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
)
from products.customer_analytics.backend.logic.membership_deletion import (
    MembershipDeletionCounts,
    MembershipDeletionInput,
    MembershipDeletionStore,
    run_membership_deletion,
)
from products.customer_analytics.backend.models.membership_cleanup import MembershipCleanupCandidate
from products.customer_analytics.backend.temporal.membership_deletion import (
    COORDINATOR_RUN_BUDGET,
    SCHEDULE_ID,
    TEAM_RUN_BUDGET,
    MembershipDeletionScheduleInput,
    MembershipDeletionTeamWorkflow,
    MembershipDeletionWorkflow,
    create_membership_deletion_schedule,
    list_membership_deletion_teams_activity,
    membership_deletion_activity,
    record_membership_deletion_team_activity,
)
from products.customer_analytics.backend.temporal.membership_discovery import (
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

    async def finish_batch(*args: object, **kwargs: object) -> MembershipDeletionCounts:
        nonlocal clock
        clock += elapsed
        return MembershipDeletionCounts(checked=100, has_more=has_more)

    execute_activity = AsyncMock(side_effect=finish_batch)
    with (
        patch("products.customer_analytics.backend.temporal.membership_deletion.MAX_BATCHES_PER_TEAM", 3),
        patch("temporalio.workflow.now", side_effect=lambda: clock),
        patch("temporalio.workflow.logger") as run_logger,
        patch(
            "temporalio.workflow.info", return_value=SimpleNamespace(start_time=now, execution_timeout=TEAM_RUN_BUDGET)
        ),
        patch("temporalio.workflow.execute_activity", execute_activity),
    ):
        result = await MembershipDeletionTeamWorkflow().run(MembershipDeletionInput(team_id=1))
    assert result.checked == 100 * expected_batches
    assert result.has_more == has_more
    summary = run_logger.info.call_args.kwargs["extra"]
    assert summary["stop_reason"] == stop_reason
    assert summary["checked"] == result.checked
    assert summary["batches"] == expected_batches
    assert summary["duration_seconds"] == elapsed.total_seconds() * expected_batches
    assert summary["dry_run"] is True
    assert summary["deletion_enabled"] is False


@pytest.mark.asyncio
async def test_coordinator_stops_between_teams_at_deadline() -> None:
    now = timezone.now()
    clock = now
    execute_activity = AsyncMock(side_effect=[[1, 2], None])

    async def finish_child(*args: object, **kwargs: object) -> MembershipDeletionCounts:
        nonlocal clock
        clock = now + COORDINATOR_RUN_BUDGET
        return MembershipDeletionCounts(checked=100, deleted=5, has_more=True)

    execute_child = AsyncMock(side_effect=finish_child)
    with (
        patch("temporalio.workflow.now", side_effect=lambda: clock),
        patch("temporalio.workflow.logger") as run_logger,
        patch("temporalio.workflow.execute_activity", execute_activity),
        patch("temporalio.workflow.execute_child_workflow", execute_child),
    ):
        await MembershipDeletionWorkflow().run(MembershipDeletionScheduleInput())
    assert execute_child.await_count == 1
    assert execute_child.call_args.args[1].team_id == 1
    assert execute_activity.call_args.args == (record_membership_deletion_team_activity, 1)
    assert execute_child.call_args.kwargs["execution_timeout"] <= TEAM_RUN_BUDGET
    summary = run_logger.info.call_args.kwargs["extra"]
    assert summary["scope"] == "coordinator"
    assert summary["stop_reason"] == "time_budget"
    assert summary["teams_completed"] == 1
    assert summary["checked"] == 100
    assert summary["deleted"] == 5
    assert summary["duration_seconds"] == COORDINATOR_RUN_BUDGET.total_seconds()


@pytest.mark.django_db(transaction=True)
def test_deletion_lease_and_network_transaction_scope(team: Team) -> None:
    team_id = team.pk + 1000000
    store = MembershipDeletionStore()
    lease = get_redis_client().lock(f"customer_analytics:membership_cleanup:{team_id}", timeout=60)
    with lease, patch.object(store, "delete_config") as delete_config:
        with pytest.raises(MembershipCleanupBusy):
            run_membership_deletion(MembershipDeletionInput(team_id=team_id), store)
        delete_config.assert_not_called()

    def delete_without_transaction(*args: object) -> None:
        assert not connection.in_atomic_block

    with patch.object(store, "delete_config", side_effect=delete_without_transaction):
        run_membership_deletion(
            MembershipDeletionInput(team_id=team_id, dry_run=False, delete_team_ids=(team_id,)), store
        )
    key = MembershipKey(group_type_index=0, group_key="test-account", distinct_id="test-person")
    MembershipCleanupCandidate.objects.for_team(team.pk).create(
        team_id=team.pk,
        key_hash=key.get_hash(),
        group_type_index=key.group_type_index,
        group_key=key.group_key,
        distinct_id=key.distinct_id,
        missing_side="person",
        first_missing_at=timezone.now() - timedelta(days=2),
        last_checked_at=timezone.now(),
    )

    def lookup_without_transaction(*args: object, **kwargs: object) -> MembershipExistence:
        assert not connection.in_atomic_block
        return MembershipExistence(persons=frozenset(), groups=frozenset())

    with (
        patch(
            "products.customer_analytics.backend.logic.membership_deletion.get_membership_existence",
            side_effect=lookup_without_transaction,
        ),
        patch.object(store, "delete_keys", side_effect=delete_without_transaction),
    ):
        assert (
            run_membership_deletion(
                MembershipDeletionInput(team_id=team.pk, dry_run=False, delete_team_ids=(team.pk,)), store
            ).deleted
            == 1
        )
    assert not MembershipCleanupCandidate.objects.for_team(team.pk).exists()


@pytest.mark.asyncio
async def test_team_summary_reports_caught_deletion_failure() -> None:
    now = timezone.now()
    with (
        patch(
            "temporalio.workflow.info", return_value=SimpleNamespace(start_time=now, execution_timeout=TEAM_RUN_BUDGET)
        ),
        patch("temporalio.workflow.now", return_value=now),
        patch("temporalio.workflow.logger") as run_logger,
        patch(
            "temporalio.workflow.execute_activity", return_value=MembershipDeletionCounts(checked=10, failed_batches=1)
        ),
    ):
        result = await MembershipDeletionTeamWorkflow().run(MembershipDeletionInput(team_id=1))
    assert result.failed_batches == 1
    summary = run_logger.info.call_args.kwargs["extra"]
    assert summary["outcome"] == "partial_failure"
    assert summary["failed_batches"] == 1
    assert summary["checked"] == 10


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("membership_cleanup_tables")
async def test_temporal_deletion_erases_discovered_membership_after_grace_period(
    team: Team, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="posthog.clickhouse.cluster")
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_deletion.BATCH_SIZE", 2)
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_discovery.BATCH_SIZE", 1)
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_discovery.TEAM_BATCH_SIZE", 1)
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_deletion.TEAM_BATCH_SIZE", 1)
    task_queue = str(uuid4())
    other_team_id = team.pk + 1000000
    distinct_ids = ["temporal-person@example.com", "temporal-second@example.com"]
    group_key = "temporal-account@example.com"

    def seed_membership() -> None:
        sync_execute(
            """INSERT INTO sharded_person_group_membership
            (team_id, group_type_index, group_key, distinct_id, first_seen, last_seen) VALUES""",
            [
                (team_id, 0, group_key, distinct_id, timezone.now(), timezone.now())
                for team_id, distinct_id in [
                    (team.pk, distinct_ids[0]),
                    (team.pk, distinct_ids[1]),
                    (other_team_id, "temporal-other@example.com"),
                ]
            ],
        )

    def mature_candidates() -> None:
        candidates = MembershipCleanupCandidate.objects.for_team(team.pk)
        assert candidates.count() == 4
        assert MembershipCleanupCandidate.objects.for_team(other_team_id).count() == 2
        candidates.update(first_missing_at=timezone.now() - timedelta(days=2))

    def assert_erased() -> None:
        assert sync_execute(
            "SELECT count() FROM person_group_membership WHERE team_id = %(team_id)s",
            {"team_id": team.pk},
        ) == [(0,)]
        assert not MembershipCleanupCandidate.objects.for_team(team.pk).exists()

    lost_result = False

    @activity.defn(name="membership_deletion_activity")
    async def retry_deleted_batch(input: MembershipDeletionInput) -> MembershipDeletionCounts:
        nonlocal lost_result
        result = await membership_deletion_activity(input)
        if not lost_result:
            lost_result = True
            raise RuntimeError("Simulated lost activity result after deletion commit")
        return result

    await database_sync_to_async(seed_membership)()
    async with await WorkflowEnvironment.start_local() as environment:
        await create_membership_discovery_schedule(environment.client)
        await create_membership_deletion_schedule(environment.client)
        description = await environment.client.get_schedule_handle(SCHEDULE_ID).describe()
        assert description.schedule.state.paused
        assert description.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        await create_membership_deletion_schedule(environment.client)
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[
                MembershipDeletionWorkflow,
                MembershipDeletionTeamWorkflow,
                MembershipDiscoveryWorkflow,
                MembershipDiscoveryTeamWorkflow,
            ],
            activities=[
                list_membership_discovery_teams_activity,
                membership_discovery_activity,
                record_membership_discovery_team_activity,
                list_membership_deletion_teams_activity,
                retry_deleted_batch,
                record_membership_deletion_team_activity,
            ],
        ):
            await environment.client.execute_workflow(
                MembershipDiscoveryWorkflow.run,
                id=str(uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )
            await database_sync_to_async(mature_candidates)()
            await environment.client.execute_workflow(
                MembershipDeletionWorkflow.run,
                MembershipDeletionScheduleInput(dry_run=False, delete_team_ids=(team.pk,)),
                id=str(uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )
    await database_sync_to_async(assert_erased)()
    assert lost_result
    mutation_logs = [record.getMessage() for record in caplog.records if record.name == "posthog.clickhouse.cluster"]
    assert any("delete_membership" in message for message in mutation_logs)
    assert all(identifier not in message for message in mutation_logs for identifier in [*distinct_ids, group_key])
