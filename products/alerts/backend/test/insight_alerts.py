from typing import Any

from posthog.schema import ChartDisplayType, EventsNode, IntervalType, TrendsFilter, TrendsQuery

from posthog.models.team import Team
from posthog.schema_enums import AlertCalculationInterval

from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.product_analytics.backend.facade.models import Insight


def create_insight_alert(team: Team, **overrides: Any) -> AlertConfiguration:
    insight = Insight.objects.create(
        team=team,
        name="insight",
        query=TrendsQuery(
            series=[EventsNode(event="$pageview")],
            interval=IntervalType.DAY,
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump(),
    )
    threshold = Threshold.objects.create(
        team=team, insight=insight, configuration={"type": "absolute", "bounds": {"upper": 100.0}}
    )
    fields: dict[str, Any] = {
        "team": team,
        "insight": insight,
        "name": "alert",
        "calculation_interval": AlertCalculationInterval.DAILY.value,
        "config": {"type": "TrendsAlertConfig", "series_index": 0},
        "condition": {"type": "absolute_value"},
        "threshold": threshold,
    }
    fields.update(overrides)
    return AlertConfiguration.objects.create(**fields)
