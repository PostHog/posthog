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

INGESTION_DETECTOR_CONFIG = {"type": "knn", "window": 14, "threshold": 0.99, "n_neighbors": 5, "method": "largest"}


@transaction.atomic
def _create_default_ingestion_alert(team: Team, user: User) -> UUID | None:
    if Insight.objects.filter(team_id=team.id, filters__default_ingestion_alert=True).exists():
        return None

    insight = Insight.objects.create(
        team=team,
        created_by=user,
        name="Event volume changes",
        description=(
            "Alert when a complete day has unusually high or low event volume. "
            "Use the KNN detector with recent daily counts. Start after 16 complete days. "
            "Weekend checks are off. Late events count on their event date. "
            "Edit the insight or alert to change these settings."
        ),
        filters={"default_ingestion_alert": True},
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": None, "name": "All events", "math": "total"}],
                "interval": "day",
                "dateRange": {"date_from": "-32d"},
            },
        },
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
            "name": "Event volume changes",
            "calculation_interval": "daily",
            "condition": {"type": "absolute_value"},
            "threshold": {"configuration": {"type": "absolute", "bounds": {}}},
            "config": {
                "type": "TrendsAlertConfig",
                "series_index": 0,
                "check_ongoing_interval": False,
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
