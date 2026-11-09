"""The chart of a platform insight firing that went out without it, added to its Slack messages.

A firing waits for one render at most, so an export stall or a full render pool sends it without its
chart. This workflow renders again on the same pool, for longer, and edits the chart into each Slack
message the firing opened. Only Slack: the other providers carry no chart, and the HogFunction path
sends its event once, so a late chart there would be a second message.
"""

import datetime as dt

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
        LATE_CHART_EDIT_WINDOW,
        LATE_CHART_RENDER_RETRY_POLICY,
        LATE_CHART_RENDER_WINDOW,
        InsightChartInputs,
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
    deliveries: tuple[AlertDeliveryRequest, ...]
    chart: RenderedChart


@activity.defn
@close_db_connections
def add_late_platform_insight_chart_activity(inputs: AddLateChartInputs) -> int:
    """Adds the chart to the Slack messages the firing opened, and returns how many it edited."""
    from products.alerts_platform.backend.facade.delivery import add_late_image  # noqa: PLC0415

    edited = 0
    waiting = 0
    for request in inputs.deliveries:
        result = add_late_image(request, chart_detail(inputs.chart))
        edited += result.edited
        waiting += result.waiting
    # A destination the firing went to through a HogFunction never gets a message to edit, so it
    # waits only while nothing is edited, and the window ends the wait for an alert that has only those.
    if not edited and waiting:
        raise ApplicationError(f"{waiting} Slack message(s) not sent yet", type=LATE_CHART_MESSAGE_PENDING)
    return edited


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
        try:
            edited = await workflow.execute_activity(
                add_late_platform_insight_chart_activity,
                AddLateChartInputs(deliveries=inputs.deliveries, chart=chart),
                start_to_close_timeout=ADD_LATE_CHART_START_TO_CLOSE,
                schedule_to_close_timeout=LATE_CHART_EDIT_WINDOW,
                retry_policy=ADD_LATE_CHART_RETRY_POLICY,
            )
        except ActivityError:
            _count("late_unsent")
            return 0
        _count("added_late" if edited else "late_unsent")
        return edited


def _count(outcome: "ChartRenderOutcome") -> None:
    safe_record(increment_chart_renders, SourceKind.INSIGHT.value, outcome)


LATE_CHART_WORKFLOWS = [InsightAlertPlatformLateChartWorkflow]
LATE_CHART_ACTIVITIES = [add_late_platform_insight_chart_activity]
