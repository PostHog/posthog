from typing import Any, Union

from django.utils import timezone
from sentry_sdk.api import capture_exception
from statshog.client.base import Tags
from statshog.defaults.django import statsd

from posthog import utils
from posthog.internal_metrics.team import get_internal_metrics_team_id


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

    try:
        team_id = get_internal_metrics_team_id()
        if team_id is not None:
            now = timezone.now()
            distinct_id = utils.get_machine_id()
            event = {"event": f"$${metric_name}", "properties": {"value": value, **(tags or {})}}
            capture_internal(event, distinct_id, None, None, now, now, team_id)
    except Exception as err:
        # Ignore errors, this is not important enough to fail API on
        capture_exception(err)
