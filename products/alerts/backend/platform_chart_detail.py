"""The chart an insight firing carries in its `source_detail`, rendered after the check.

A render takes up to `RENDER_TIMEOUT`, so the check only marks the firings that want one, and the
evaluation workflow renders once the check has given back its pool slot. This module has no Django
imports, so the workflow can call it.
"""

from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.contracts import AlertDeliveryRequest, SourceBatchEvaluation

# Started by name, because the module that defines it imports the evaluation workflow's render.
LATE_CHART_WORKFLOW = "insight-alert-platform-late-chart"

# Never recorded: the workflow replaces it with the chart's ids, or drops it when the render fails.
CHART_PENDING_KEY = "insight_chart_pending_alert_id"
# The ids rather than a URL, because the URL opens the chart without a login and history keeps
# them for its whole retention. A delivery mints the URL when it sends.
CHART_ASSET_ID_KEY = "insight_chart_asset_id"
CHART_RENDER_USER_ID_KEY = "insight_chart_render_user_id"


@frozen
class RenderedChart:
    asset_id: int
    render_user_id: int


@frozen
class LateChartInputs:
    """A firing that went out without its chart, and the deliveries that sent it."""

    team_id: int
    alert_id: str
    deliveries: tuple[AlertDeliveryRequest, ...]


def chart_detail(chart: RenderedChart) -> dict[str, Any]:
    """The chart's ids, under the keys a firing's `source_detail` carries them."""
    return {CHART_ASSET_ID_KEY: chart.asset_id, CHART_RENDER_USER_ID_KEY: chart.render_user_id}


def pending_chart_alert_id(evaluation: SourceBatchEvaluation) -> str | None:
    """The legacy alert whose chart this check's firings wait for, or None when none wants one."""
    for outcome in evaluation.outcomes:
        for group in outcome.groups:
            alert_id = group.source_detail.get(CHART_PENDING_KEY)
            if alert_id is not None:
                return str(alert_id)
    return None


def with_chart(evaluation: SourceBatchEvaluation, chart: RenderedChart | None) -> SourceBatchEvaluation:
    """The evaluation with every pending firing given the chart, or left without one when it is None.

    One render serves every firing of a check, because they all show the same insight.
    """
    if pending_chart_alert_id(evaluation) is None:
        return evaluation
    return replace(
        evaluation,
        outcomes=tuple(
            replace(
                outcome,
                groups=tuple(
                    replace(group, source_detail=_resolved(group.source_detail, chart))
                    if CHART_PENDING_KEY in group.source_detail
                    else group
                    for group in outcome.groups
                ),
            )
            for outcome in evaluation.outcomes
        ),
    )


def _resolved(source_detail: dict[str, Any], chart: RenderedChart | None) -> dict[str, Any]:
    detail = {key: value for key, value in source_detail.items() if key != CHART_PENDING_KEY}
    return {**detail, **chart_detail(chart)} if chart is not None else detail
