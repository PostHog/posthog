"""The chart of a platform insight firing that went out without it, added to its Slack messages.

A firing waits for one render at most, so an export stall or a full render pool sends it without its
chart. This workflow renders again on the same pool, for longer, and edits the chart into each Slack
message the firing opened. Only Slack: the other providers carry no chart, and the HogFunction path
sends its event once, so a late chart there would be a second message.
"""

import asyncio
import datetime as dt
from dataclasses import replace

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

    from products.alerts.backend.platform_chart_detail import (
        LATE_CHART_WORKFLOW,
        LateChartInputs,
        RenderedChart,
        chart_detail,
    )
    from products.alerts.backend.temporal.platform_evaluate import (
        CHART_START_TO_CLOSE,
        LATE_CHART_RENDER_RETRY_POLICY,
        LATE_CHART_RENDER_WINDOW,
        InsightChartInputs,
        late_chart_edit_window,
        render_platform_insight_chart_activity,
    )
    from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, SourceKind
    from products.alerts_platform.backend.facade.platform_metrics import (
        ChartRenderOutcome,
        increment_chart_renders,
        safe_record,
    )

ADD_LATE_CHART_START_TO_CLOSE = dt.timedelta(seconds=30)
ADD_LATE_CHART_RETRY_POLICY = RetryPolicy(
    initial_interval=dt.timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=dt.timedelta(minutes=1),
)
# Raised while no Slack message of the firing exists yet, for a retry once its delivery sends one.
LATE_CHART_MESSAGE_PENDING = "LateChartMessagePending"


@frozen
class AddLateChartInputs:
    # One part of one delivery, so each activity stays bounded however many parts a firing splits into.
    delivery: AlertDeliveryRequest
    chart: RenderedChart


@activity.defn
@close_db_connections
def add_late_platform_insight_chart_activity(inputs: AddLateChartInputs) -> int:
    """Adds the chart to the Slack messages the firing opened, and returns how many it edited."""
    from products.alerts_platform.backend.facade.delivery import add_late_image  # noqa: PLC0415

    result = add_late_image(inputs.delivery, chart_detail(inputs.chart))
    # An edit already made is a no-op on retry, so every message still waiting gets another attempt.
    if result.waiting:
        raise ApplicationError(f"{result.waiting} Slack message(s) not edited yet", type=LATE_CHART_MESSAGE_PENDING)
    return result.edited


@workflow.defn(name=LATE_CHART_WORKFLOW)
class InsightAlertPlatformLateChartWorkflow(PostHogWorkflow):
    inputs_cls = LateChartInputs

    @workflow.run
    async def run(self, inputs: LateChartInputs) -> int:
        try:
            chart = await workflow.execute_activity(
                render_platform_insight_chart_activity,
                InsightChartInputs(team_id=inputs.team_id, alert_id=inputs.alert_id, raise_on_failed_render=True),
                start_to_close_timeout=CHART_START_TO_CLOSE,
                schedule_to_close_timeout=LATE_CHART_RENDER_WINDOW,
                retry_policy=LATE_CHART_RENDER_RETRY_POLICY,
            )
        except ActivityError:
            _count("late_render_failed")
            return 0
        if chart is None:
            return 0
        # The evaluation's request names every part, and the delivery workflow sends each part on its own.
        parts = [replace(request, part=part) for request in inputs.deliveries for part in range(max(request.parts, 1))]
        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    add_late_platform_insight_chart_activity,
                    AddLateChartInputs(delivery=part, chart=chart),
                    start_to_close_timeout=ADD_LATE_CHART_START_TO_CLOSE,
                    schedule_to_close_timeout=late_chart_edit_window(inputs),
                    retry_policy=ADD_LATE_CHART_RETRY_POLICY,
                )
                for part in parts
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, ActivityError):
                raise result
        edited = sum(result for result in results if isinstance(result, int))
        unsent = any(isinstance(result, ActivityError) for result in results)
        _count("late_unsent" if unsent or not edited else "added_late")
        return edited


def _count(outcome: "ChartRenderOutcome") -> None:
    safe_record(increment_chart_renders, SourceKind.INSIGHT.value, outcome)


LATE_CHART_WORKFLOWS = [InsightAlertPlatformLateChartWorkflow]
LATE_CHART_ACTIVITIES = [add_late_platform_insight_chart_activity]
