from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction

import structlog

from posthog.email import is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false

from products.alerts_platform.backend.facade.scheduling import CalendarInterval, alert_check_offset
from products.product_analytics.backend.facade.models import Insight

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

INGESTION_QUERY = """
SELECT
    day,
    event_count,
    previous_count,
    event_count - previous_count AS count_change,
    100.0 * (event_count - previous_count) / nullIf(previous_count, 0) AS change_percent,
    CASE
        WHEN previous_count = 0 OR abs(event_count - previous_count) < 100 THEN 0
        ELSE 100.0 * (event_count - previous_count) / previous_count
    END AS significant_change_percent
FROM (
    SELECT
        day,
        event_count,
        lagInFrame(event_count, 1, 0) OVER (
            ORDER BY day ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS previous_count
    FROM (
        SELECT calendar.day AS day, toFloat(ifNull(counts.event_count, 0)) AS event_count
        FROM (
            SELECT addDays(toStartOfDay(now()), toInt(arrayJoin(range(32))) - 32) AS day
        ) AS calendar
        LEFT JOIN (
            SELECT toStartOfDay(created_at) AS day, count() AS event_count
            FROM events
            WHERE created_at >= addDays(toStartOfDay(now()), -32)
                AND created_at < toStartOfDay(now())
            GROUP BY day
        ) AS counts ON calendar.day = counts.day
    )
)
ORDER BY day
"""

INGESTION_DETECTOR_CONFIG = {
    "type": "ensemble",
    "operator": "and",
    "detectors": [
        {"type": "zscore", "window": 14, "threshold": 0.95},
        {"type": "threshold", "lower_bound": -50, "upper_bound": 50},
    ],
}


@transaction.atomic
def _create_default_ingestion_alert(team: Team, user: User) -> UUID | None:
    if Insight.objects.filter(team_id=team.id, filters__default_ingestion_alert=True).exists():
        return None

    insight = Insight.objects.create(
        team=team,
        created_by=user,
        name="Event ingestion changes",
        description=(
            "Compare each complete day with the previous day by ingestion time. "
            "Alert on unusual changes above 50% and at least 100 events. "
            "Use 14 previous daily changes as history. Start after 16 complete days. "
            "Weekend checks are off. Edit the insight or alert to change these settings."
        ),
        filters={"default_ingestion_alert": True},
        query={"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": INGESTION_QUERY}},
    )
    first_check_date = team.created_at.astimezone(ZoneInfo(team.timezone)).date() + timedelta(days=17)
    first_check_at = datetime.combine(first_check_date, time(1), tzinfo=ZoneInfo(team.timezone)).astimezone(UTC)
    from products.alerts.backend.presentation.views.alert import (
        AlertSerializer,  # noqa: PLC0415 — keeps API dependencies off team creation startup
    )

    alert = AlertSerializer.create_for_user(
        team=team,
        user=user,
        data={
            "insight": insight.id,
            "name": "Event ingestion changes",
            "calculation_interval": "daily",
            "condition": {"type": "absolute_value"},
            "threshold": {"configuration": {"type": "absolute", "bounds": {}}},
            "config": {
                "type": "HogQLAlertConfig",
                "evaluation": "last_row",
                "column": "significant_change_percent",
                "label_column": "day",
            },
            "detector_config": INGESTION_DETECTOR_CONFIG,
            "enabled": is_email_available(),
            "skip_weekend": True,
            "subscribed_users": [user.id],
        },
    )
    alert.next_check_at = first_check_at + alert_check_offset(CalendarInterval.DAILY, alert.id)
    alert.save()
    return alert.id


def create_default_ingestion_alert(team: Team, user: User | None) -> UUID | None:
    if user is None or not user.is_active or user.distinct_id is None or team.is_demo:
        return None
    if not feature_enabled_or_false(
        "default-ingestion-alert",
        user.distinct_id,
        groups={"organization": str(team.organization_id)},
        only_evaluate_locally=True,
    ):
        return None
    try:
        return _create_default_ingestion_alert(team, user)
    except Exception as error:
        logger.exception("default_ingestion_alert_creation_failed", team_id=team.id)
        capture_exception(error)
        return None
