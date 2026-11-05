import logging
from datetime import timedelta
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, patch

from django.db import connection
from django.utils import timezone

from temporalio.client import ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.redis import get_client as get_redis_client
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.logic.membership import MembershipExistence, MembershipKey
from products.customer_analytics.backend.logic.membership_cleanup import (
    MembershipCleanupCounts,
    MembershipCleanupInput,
    MembershipCleanupStore,
    run_membership_cleanup,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)
from products.customer_analytics.backend.temporal.membership_cleanup import (
    COORDINATOR_RUN_BUDGET,
    SCHEDULE_ID,
    TEAM_RUN_BUDGET,
    MembershipCleanupScheduleInput,
    MembershipCleanupTeamWorkflow,
    MembershipCleanupWorkflow,
    create_membership_cleanup_schedule,
    list_membership_cleanup_teams_activity,
    membership_cleanup_activity,
    record_membership_cleanup_team_activity,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_more,elapsed,expected_batches",
    [(False, timedelta(), 1), (True, timedelta(), 3), (True, TEAM_RUN_BUDGET, 1)],
)
async def test_team_workflow_stops_at_scan_or_run_limit(
    has_more: bool, elapsed: timedelta, expected_batches: int
) -> None:
    now = timezone.now()
    execute_activity = AsyncMock(return_value=MembershipCleanupCounts(scanned=100, has_more=has_more))
    with (
        patch("products.customer_analytics.backend.temporal.membership_cleanup.MAX_BATCHES_PER_TEAM", 3),
        patch("temporalio.workflow.now", side_effect=[now, *[now + elapsed] * 3]),
        patch("temporalio.workflow.execute_activity", execute_activity),
    ):
        result = await MembershipCleanupTeamWorkflow().run(MembershipCleanupInput(team_id=1))
    assert result.scanned == 100 * expected_batches
    assert result.has_more == has_more


@pytest.mark.asyncio
async def test_coordinator_stops_between_teams_at_deadline() -> None:
    now = timezone.now()
    execute_activity = AsyncMock(side_effect=[[1, 2], None])
    execute_child = AsyncMock()
    with (
        patch("temporalio.workflow.now", side_effect=[now, now, now, now + COORDINATOR_RUN_BUDGET]),
        patch("temporalio.workflow.execute_activity", execute_activity),
        patch("temporalio.workflow.execute_child_workflow", execute_child),
    ):
        await MembershipCleanupWorkflow().run(MembershipCleanupScheduleInput())
    assert execute_child.await_count == 1
    assert execute_child.call_args.args[1].team_id == 1
    assert execute_activity.call_args.args == (record_membership_cleanup_team_activity, 1)
    assert execute_child.call_args.kwargs["execution_timeout"] <= TEAM_RUN_BUDGET


@pytest.mark.django_db(transaction=True)
def test_cleanup_lease_excludes_overlapping_attempts_and_network_transactions(team: Team) -> None:
    team_id = 1000001
    store = MembershipCleanupStore()
    lease = get_redis_client().lock(f"customer_analytics:membership_cleanup:{team_id}", timeout=60)
    with lease, patch.object(store, "list_keys") as list_keys:
        assert run_membership_cleanup(MembershipCleanupInput(team_id=team_id), store).scanned == 0
        list_keys.assert_not_called()

    def list_keys_without_transaction(*args: object) -> list[MembershipKey]:
        assert not connection.in_atomic_block
        return []

    def delete_without_transaction(*args: object) -> None:
        assert not connection.in_atomic_block

    with (
        patch.object(store, "list_keys", side_effect=list_keys_without_transaction),
        patch.object(store, "delete_config", side_effect=delete_without_transaction),
    ):
        run_membership_cleanup(
            MembershipCleanupInput(team_id=team_id, dry_run=False, delete_team_ids=(team_id,)), store
        )
    assert not MembershipCleanupScan.objects.for_team(team_id).exists()
    assert not MembershipCleanupCandidate.objects.for_team(team_id).exists()

    key = MembershipKey(group_type_index=0, group_key="test-account", distinct_id="test-person")

    def lookup_without_transaction(*args: object) -> MembershipExistence:
        assert not connection.in_atomic_block
        return MembershipExistence(persons=frozenset(), groups=frozenset())

    with (
        patch.object(store, "list_keys", return_value=[key]),
        patch(
            "products.customer_analytics.backend.logic.membership_cleanup.get_membership_existence",
            side_effect=lookup_without_transaction,
        ),
    ):
        assert run_membership_cleanup(MembershipCleanupInput(team_id=team.pk), store).scanned == 1
    assert MembershipCleanupCandidate.objects.for_team(team.pk).count() == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("membership_cleanup_tables")
async def test_temporal_cleanup_erases_membership_after_grace_period(
    team: Team, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="posthog.clickhouse.cluster")
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_cleanup.BATCH_SIZE", 1)
    monkeypatch.setattr("products.customer_analytics.backend.logic.membership_cleanup.TEAM_BATCH_SIZE", 1)
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

    await database_sync_to_async(seed_membership)()
    async with await WorkflowEnvironment.start_local() as environment:
        await create_membership_cleanup_schedule(environment.client)
        description = await environment.client.get_schedule_handle(SCHEDULE_ID).describe()
        assert description.schedule.state.paused
        assert description.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        await create_membership_cleanup_schedule(environment.client)
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[MembershipCleanupWorkflow, MembershipCleanupTeamWorkflow],
            activities=[
                list_membership_cleanup_teams_activity,
                membership_cleanup_activity,
                record_membership_cleanup_team_activity,
            ],
        ):
            await environment.client.execute_workflow(
                MembershipCleanupWorkflow.run,
                MembershipCleanupScheduleInput(),
                id=str(uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )
            await database_sync_to_async(mature_candidates)()
            await environment.client.execute_workflow(
                MembershipCleanupWorkflow.run,
                MembershipCleanupScheduleInput(dry_run=False, delete_team_ids=(team.pk,)),
                id=str(uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=1),
            )
    await database_sync_to_async(assert_erased)()
    mutation_logs = [record.getMessage() for record in caplog.records if record.name == "posthog.clickhouse.cluster"]
    assert any("delete_membership" in message for message in mutation_logs)
    assert all(identifier not in message for message in mutation_logs for identifier in [*distinct_ids, group_key])
