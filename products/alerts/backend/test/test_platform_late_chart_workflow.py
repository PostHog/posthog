import uuid
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from unittest.mock import patch

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.platform_chart_detail import LateChartInputs, RenderedChart
from products.alerts.backend.temporal.platform_evaluate import (
    CHART_RENDER_FAILED,
    CHART_RENDER_TIMED_OUT,
    InsightChartInputs,
)
from products.alerts.backend.temporal.platform_late_chart import (
    LATE_CHART_MESSAGE_PENDING,
    AddLateChartInputs,
    InsightAlertPlatformLateChartWorkflow,
)
from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, SourceKind

QUEUE = "test-platform-insight-late-chart"
CHART = RenderedChart(asset_id=7, render_user_id=3)
DELIVERY = AlertDeliveryRequest(
    source=SourceKind.INSIGHT,
    team_id=1,
    configuration_id="00000000-0000-0000-0000-000000000001",
    evaluation_key="slot:2026-09-16T10:00:00+00:00",
    destination_alert_id="legacy-alert",
    event_ids_by_kind={"firing": "$insight_alert_firing"},
    owned_by_platform=True,
)


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.parametrize(
    "renders, edits, expected_edited, expected_outcomes",
    [
        pytest.param("failed", None, 0, ["late_render_failed"], id="export_stalls_past_the_window"),
        pytest.param("pool_full_once", 1, 1, ["added_late"], id="pool_frees_then_chart_lands"),
        pytest.param("timed_out_once", 1, 1, ["added_late"], id="stall_clears_then_chart_lands"),
        pytest.param("none", None, 0, [], id="no_chart_applies_any_more"),
        pytest.param("rendered", "pending", 0, ["late_unsent"], id="no_native_message_to_edit"),
    ],
)
async def test_a_late_chart_renders_again_and_reaches_the_firing_message(
    environment: WorkflowEnvironment,
    renders: str,
    edits: int | str | None,
    expected_edited: int,
    expected_outcomes: list[str],
) -> None:
    edited_with: list[AddLateChartInputs] = []
    counted: list[str] = []

    @activity.defn(name="render_platform_insight_chart_activity")
    async def render(inputs: InsightChartInputs) -> RenderedChart | None:
        assert inputs.raise_on_failed_render
        if renders == "failed":
            raise ApplicationError("export timed out", type=CHART_RENDER_FAILED)
        if renders == "pool_full_once" and activity.info().attempt == 1:
            raise ApplicationError("render pool full")
        if renders == "timed_out_once" and activity.info().attempt == 1:
            raise ApplicationError("export timed out", type=CHART_RENDER_TIMED_OUT)
        return None if renders == "none" else CHART

    @activity.defn(name="add_late_platform_insight_chart_activity")
    async def add(inputs: AddLateChartInputs) -> int:
        edited_with.append(inputs)
        if edits == "pending":
            raise ApplicationError("not sent yet", type=LATE_CHART_MESSAGE_PENDING)
        return int(edits or 0)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertPlatformLateChartWorkflow],
        activities=[render, add],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        with patch(
            "products.alerts.backend.temporal.platform_late_chart.increment_chart_renders",
            side_effect=lambda _source, outcome: counted.append(outcome),
        ):
            edited = await environment.client.execute_workflow(
                InsightAlertPlatformLateChartWorkflow.run,
                LateChartInputs(team_id=1, alert_id="legacy-alert", deliveries=(DELIVERY,)),
                id=f"test-{uuid.uuid4()}",
                task_queue=QUEUE,
            )

    assert edited == expected_edited
    assert all(inputs == AddLateChartInputs(delivery=DELIVERY, chart=CHART) for inputs in edited_with)
    assert (len(edited_with) > 1) is (edits == "pending")
    assert counted == expected_outcomes


async def test_a_late_chart_edits_each_part_of_a_split_delivery_in_its_own_activity(
    environment: WorkflowEnvironment,
) -> None:
    edited_parts: list[int] = []

    @activity.defn(name="render_platform_insight_chart_activity")
    async def render(inputs: InsightChartInputs) -> RenderedChart:
        return CHART

    @activity.defn(name="add_late_platform_insight_chart_activity")
    async def add(inputs: AddLateChartInputs) -> int:
        edited_parts.append(inputs.delivery.part)
        return 1

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertPlatformLateChartWorkflow],
        activities=[render, add],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        edited = await environment.client.execute_workflow(
            InsightAlertPlatformLateChartWorkflow.run,
            LateChartInputs(team_id=1, alert_id="legacy-alert", deliveries=(replace(DELIVERY, parts=3),)),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

    assert (edited, sorted(edited_parts)) == (3, [0, 1, 2])
