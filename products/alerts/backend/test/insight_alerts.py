from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

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


def move_to_platform(alert: AlertConfiguration, *, at: datetime | None = None) -> None:
    """Hands an insight alert to the platform, as a create does for a new one."""
    from products.alerts.backend.platform_cutover import hand_over  # noqa: PLC0415

    with transaction.atomic():
        locked = (
            AlertConfiguration.objects.select_for_update(of=("self",))
            .select_related("team", "threshold")
            .get(id=alert.id)
        )
        assert hand_over(locked, at or timezone.now())
    alert.refresh_from_db()
