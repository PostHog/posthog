import re
from typing import Any, Dict, List, Optional, Union

from constance import config, settings
from rest_framework import exceptions, mixins, permissions, serializers, viewsets

from posthog.permissions import IsStaffUser
from posthog.settings import SETTINGS_ALLOWING_API_OVERRIDE

from datetime import datetime
from typing import Any, Dict, List, Union

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from posthog.permissions import IsStaffUser
from posthog.version import VERSION



DEAD_LETTER_QUEUE_METRICS = {
    "dlq_size": {
        "metric": "Total events in dead letter queue", 
        "fn": lambda : { "value": get_dead_letter_queue_size() },
    },
    "dlq_events_last_24h": {
        "metric": "Events sent to dead letter queue in the last 24h",
        "fn": lambda : { "value": get_dead_letter_queue_events_last_24h() },
    },
    "dlq_last_error_timestamp": {
        "metric": "Last error timestamp",
        "fn": lambda : { "value": get_dlq_last_error_timestamp() },
    },
    "dlq_events_per_error": {
        "metric": "Total events per error",
        "fn": lambda : { "subrows": { "columns": ["Error", "Total events"], "rows": get_dead_letter_queue_events_per_error() } },
    },
    "dlq_events_per_location": {
        "metric": "Total events per error location",
        "fn": lambda : { "subrows": { "columns": ["Error location", "Total events"], "rows": get_dead_letter_queue_events_per_location() } },
    },
    "dlq_events_per_day": {
        "metric": "Total events per day",
        "fn": lambda : { "subrows": { "columns": ["Date", "Total events"], "rows": get_dead_letter_queue_events_per_day() } },
    }
,
}

class DeadLetterQueueMetric(object):
    key: str = ""
    metric: str = ""
    value: Union[str, bool, int, None] = None
    subrows: Optional[List[Any]] = None

    def __init__(self, **kwargs):
        for field in ("key", "value", "value", "subrows"):
            setattr(self, field, kwargs.get(field, None))


def get_dlq_metric(key: str) -> DeadLetterQueueMetric:

    metric_context =  DEAD_LETTER_QUEUE_METRICS[key]
    metric = metric_context | metric_context["fn"]()


    return DeadLetterQueueMetric(
        key=key,
        metric=metric.get("metric"),
        value=metric.get("value"),
        subrows=metric.get("subrows")
    )


class DeadLetterQueueMetricsSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    metric = serializers.CharField(read_only=True)
    value = serializers.JSONField(read_only=True)  
    subrows = serializers.JSONField(read_only=True)  


class DeadLetterQueueViewSet(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin
):
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]
    serializer_class = DeadLetterQueueMetricsSerializer
    lookup_field = "key"

    def get_queryset(self):
        output = []
        for key, metric_context in DEAD_LETTER_QUEUE_METRICS.items():
            fn_result = metric_context["fn"]()
            del  metric_context["fn"]
            metric = { "key": key, **fn_result, **metric_context }
            output.append(metric)
        return output

    def get_object(self) -> DeadLetterQueueMetric:
        # Perform the lookup filtering.
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        key = self.kwargs[lookup_url_kwarg]

        if key not in settings.CONFIG:
            raise exceptions.NotFound(f"Setting with key `{key}` does not exist.")

        return get_dlq_metric(key)

def get_dead_letter_queue_size() -> int:
    return sync_execute("SELECT count(*) FROM events_dead_letter_queue")[0][0]


def get_dlq_last_error_timestamp() -> int:
    ts = sync_execute("SELECT max(error_timestamp) FROM events_dead_letter_queue")[0][0]

    last_error_timestamp = "-" if ts.timestamp() == datetime(1970, 1, 1).timestamp() else ts
    return last_error_timestamp


def get_dead_letter_queue_events_last_24h() -> int:
    return sync_execute(
        "SELECT count(*) FROM events_dead_letter_queue WHERE error_timestamp >= (NOW() - INTERVAL 1 DAY)"
    )[0][0]


def get_dead_letter_queue_events_per_error() -> List[Union[str, int]]:
    return sync_execute(
        "SELECT error, count(*) AS c FROM events_dead_letter_queue GROUP BY error ORDER BY c DESC LIMIT 10"
    )


def get_dead_letter_queue_events_per_location() -> List[Union[str, int]]:
    return sync_execute(
        "SELECT error_location, count(*) AS c FROM events_dead_letter_queue GROUP BY error_location ORDER BY c DESC LIMIT 10"
    )


def get_dead_letter_queue_events_per_day() -> List[Union[str, int]]:
    return sync_execute(
        "SELECT toDate(error_timestamp) as day, count(*) AS c FROM events_dead_letter_queue GROUP BY day ORDER BY c DESC LIMIT 10"
    )
