import uuid
from collections.abc import AsyncIterator

import pytest
from unittest.mock import patch

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.platform_chart_detail import LateChartInputs, RenderedChart
from products.alerts.backend.temporal.platform_evaluate import CHART_RENDER_FAILED, InsightChartInputs
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
        # The export stalls past the window, so the firing keeps the message it went out with.
        ("failed", None, 0, ["late_render_failed"]),
        # A full pool, then a render: the chart reaches the message.
        ("pool_full_once", 1, 1, ["added_late"]),
        # No chart applies any more, so nothing is edited or counted.
        ("none", None, 0, []),
        # The firing never reached a native Slack message, such as one sent through a HogFunction.
        ("rendered", "pending", 0, ["late_unsent"]),
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
    assert all(inputs == AddLateChartInputs(deliveries=(DELIVERY,), chart=CHART) for inputs in edited_with)
    assert (len(edited_with) > 1) is (edits == "pending")
    assert counted == expected_outcomes
