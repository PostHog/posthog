from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

import pytest_asyncio
from temporalio.api.enums.v1 import EventType
from temporalio.client import ScheduleIntervalSpec, ScheduleOverlapPolicy
from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.entitlements import repair
from posthog.temporal.entitlement_reactions import repair as repair_workflow
from posthog.temporal.entitlement_reactions.registration import ACTIVITIES, WORKFLOWS
from posthog.temporal.entitlement_reactions.repair import EntitlementRepairInputs, EntitlementRepairWorkflow
from posthog.temporal.entitlement_reactions.schedule import create_entitlement_repair_schedule
from posthog.temporal.entitlement_reactions.test_dispatch import integration as integration
from posthog.temporal.entitlement_reactions.test_workflow import (
    persisted,
    set_source,
    setup_organization,
    temporal_environment as temporal_environment,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="module")
def sdk_metrics() -> MetricBuffer:
    return MetricBuffer(1000)


@pytest.fixture(scope="module")
def runtime(sdk_metrics: MetricBuffer) -> Runtime:
    return Runtime(telemetry=TelemetryConfig(metrics=sdk_metrics))


@pytest_asyncio.fixture
async def metrics_environment(runtime: Runtime) -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping(runtime=runtime) as env:
        yield env


@pytest.mark.usefixtures("integration")
@pytest.mark.parametrize("behind_count", [0, 2])
async def test_repair_run_reports_organizations_behind_across_pages(
    metrics_environment: WorkflowEnvironment,
    sdk_metrics: MetricBuffer,
    monkeypatch: pytest.MonkeyPatch,
    behind_count: int,
) -> None:
    await setup_organization(baseline=True)
    for _ in range(behind_count):
        await set_source(await setup_organization(baseline=True), 2)
    monkeypatch.setattr(repair, "CANDIDATE_PAGE_SIZE", 1)
    monkeypatch.setattr(repair_workflow, "MAX_PAGES_PER_RUN", 2)
    sdk_metrics.retrieve_updates()
    with patch("posthog.entitlements.dispatch.async_connect", AsyncMock(side_effect=RuntimeError("handoff"))):
        async with Worker(
            metrics_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await metrics_environment.client.execute_workflow(
                EntitlementRepairWorkflow.run,
                EntitlementRepairInputs(),
                id="repair-gauge",
                task_queue=settings.BILLING_TASK_QUEUE,
                execution_timeout=timedelta(seconds=30),
            )
    counted = sum(
        update.value
        for update in sdk_metrics.retrieve_updates()
        if update.metric.name == "entitlement_reactions_organizations_behind"
    )
    assert counted == behind_count


async def test_repair_retries_failed_handoff_on_later_sweep(temporal_environment, integration, monkeypatch) -> None:
    ids = sorted([await setup_organization(baseline=True), await setup_organization(baseline=True)])
    for org_id in ids:
        await set_source(org_id, 2)
    monkeypatch.setattr(repair, "CANDIDATE_PAGE_SIZE", 1)
    monkeypatch.setattr(repair_workflow, "MAX_PAGES_PER_RUN", 2)
    connect = AsyncMock(side_effect=[RuntimeError("handoff"), temporal_environment.client])
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await temporal_environment.client.start_workflow(
                EntitlementRepairWorkflow.run,
                EntitlementRepairInputs(),
                id="repair-first",
                task_queue=settings.BILLING_TASK_QUEUE,
                execution_timeout=timedelta(seconds=30),
            )
            await handle.result()
            history = await temporal_environment.client.get_workflow_handle(
                "repair-first", run_id=handle.result_run_id
            ).fetch_history()
            assert any(e.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW for e in history.events)
            assert sum(e.event_type == EventType.EVENT_TYPE_TIMER_STARTED for e in history.events) == 2
            await temporal_environment.client.get_workflow_handle(f"entitlement-reactions-{ids[1]}").result()
            assert (await persisted(ids[0]))["behind"] == ["fixture"]
            assert (await persisted(ids[1]))["product"] == 2
            connect.side_effect = None
            connect.return_value = temporal_environment.client
            await temporal_environment.client.execute_workflow(
                EntitlementRepairWorkflow.run,
                EntitlementRepairInputs(),
                id="repair-second",
                task_queue=settings.BILLING_TASK_QUEUE,
                execution_timeout=timedelta(seconds=30),
            )
            await temporal_environment.client.get_workflow_handle(f"entitlement-reactions-{ids[0]}").result()
            assert (await persisted(ids[0]))["product"] == 2
            assert integration["seen"] == [2, 2]


async def test_schedule_does_not_trigger_on_creation() -> None:
    client = MagicMock()
    client.get_schedule_handle.return_value.describe = AsyncMock(
        side_effect=RPCError("missing", RPCStatusCode.NOT_FOUND, b"")
    )
    client.create_schedule = AsyncMock()
    await create_entitlement_repair_schedule(client)
    request = client.create_schedule.call_args.kwargs
    assert request["trigger_immediately"] is False
    schedule = request["schedule"]
    assert schedule.spec.intervals == [ScheduleIntervalSpec(every=timedelta(minutes=30), offset=timedelta(minutes=2))]
    assert schedule.spec.jitter == timedelta(minutes=5)
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.action.task_queue == settings.BILLING_TASK_QUEUE
