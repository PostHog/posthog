from datetime import timezone
from typing import Any, Optional, Union

from django.conf import settings
from sentry_sdk.api import capture_exception
from statshog.client.base import Tags
from statshog.defaults.django import statsd

from posthog.utils import get_machine_id

NAME = "Posthog Internal Metrics"


def timing(metric_name: str, ms: float, tags: Tags = None):
    statsd.timing(metric_name, ms, tags=tags)
    _capture(metric_name, ms, tags)


def gauge(metric_name: str, value: Union[int, float], tags: Tags = None):
    statsd.gauge(metric_name, value, tags=tags)
    _capture(metric_name, value, tags)


def incr(metric_name: str, count: int = 1, tags: Tags = None):
    statsd.incr(metric_name, count, tags=tags)
    _capture(metric_name, count, tags)


def _capture(metric_name: str, value: Any, tags: Tags):
    from posthog.api.capture import capture_internal

    team_id = get_internal_metrics_team_id()
    if team_id is not None:
        now = timezone.now()
        distinct_id = get_machine_id()
        event = {"event": f"$${metric_name}", "properties": {"value": value, **tags}}
        capture_internal(event, distinct_id, None, None, now, now, team_id)


_cached_internal_team_id: Optional[int] = None


def get_internal_metrics_team_id() -> Optional[int]:
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    global _cached_internal_team_id

    if not settings.CAPTURE_INTERNAL_METRICS:
        return None
    if _cached_internal_team_id is not None:
        return _cached_internal_team_id

    try:
        team = Team.objects.filter(organization__for_internal_metrics=True).first()

        if team is None:
            organization = Organization.objects.create(name=NAME, for_internal_metrics=True)
            team = Team.objects.create(
                name=NAME,
                default_dashboards=False,
                organization=organization,
                ingested_event=True,
                completed_snippet_onboarding=True,
                is_demo=True,
            )

        _cached_internal_team_id = team.pk

        return team.pk
    except:
        # Ignore errors during team finding/creation.
        capture_exception()

        return None
