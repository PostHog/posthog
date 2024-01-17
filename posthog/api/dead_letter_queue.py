from datetime import datetime
from typing import Any, List, Optional, Union

from rest_framework import mixins, permissions, serializers, viewsets

from posthog.client import sync_execute
from posthog.permissions import IsStaffUser

# keep in sync with posthog/frontend/src/scenes/instance/DeadLetterQueue/MetricsTab.tsx
ROWS_LIMIT = 10

DEAD_LETTER_QUEUE_METRICS = {
    "dlq_size": {
        "metric": "Total events in dead letter queue",
        "fn": lambda _: {"value": get_dead_letter_queue_size()},
    },
    "dlq_events_last_24h": {
        "metric": "Events sent to dead letter queue in the last 24h",
        "fn": lambda _: {"value": get_dead_letter_queue_events_last_24h()},
    },
    "dlq_last_error_timestamp": {
        "metric": "Last error timestamp",
        "fn": lambda _: {"value": get_dlq_last_error_timestamp()},
    },
    "dlq_events_per_error": {
        "metric": "Total events per error",
        "fn": lambda offset: {
            "subrows": {
                "columns": ["Error", "Total events"],
                "rows": get_dead_letter_queue_events_per_error(offset),
            }
        },
    },
    "dlq_events_per_location": {
        "metric": "Total events per error location",
        "fn": lambda offset: {
            "subrows": {
                "columns": ["Error location", "Total events"],
                "rows": get_dead_letter_queue_events_per_location(offset),
            }
        },
    },
    "dlq_events_per_day": {
        "metric": "Total events per day",
        "fn": lambda offset: {
            "subrows": {
                "columns": ["Date", "Total events"],
                "rows": get_dead_letter_queue_events_per_day(offset),
            }
        },
    },
    "dlq_events_per_tag": {
        "metric": "Total events per tag",
        "fn": lambda offset: {
            "subrows": {
                "columns": ["Date", "Total events"],
                "rows": get_dead_letter_queue_events_per_tag(offset),
            }
        },
    },
}


class DeadLetterQueueMetric:
    key: str = ""
    metric: str = ""
    value: Union[str, bool, int, None] = None
    subrows: Optional[List[Any]] = None

    def __init__(self, **kwargs):
        for field in ("key", "metric", "value", "subrows"):
            setattr(self, field, kwargs.get(field, None))


def get_dlq_metric(key: str, offset: Optional[int] = 0) -> DeadLetterQueueMetric:
    metric_context = DEAD_LETTER_QUEUE_METRICS[key]
    fn_result = metric_context["fn"](offset)  # type: ignore

    return DeadLetterQueueMetric(
        key=key,
        metric=metric_context.get("metric"),
        value=metric_context.get("value"),
        subrows=fn_result.get("subrows"),
    )


class DeadLetterQueueMetricsSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    metric = serializers.CharField(read_only=True)
    value = serializers.JSONField(read_only=True)
    subrows = serializers.JSONField(read_only=True)


class DeadLetterQueueViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    permission_classes = [permissions.IsAuthenticated, IsStaffUser]
    serializer_class = DeadLetterQueueMetricsSerializer
    lookup_field = "key"

    def get_queryset(self):
        output = []
        for key, metric_context in DEAD_LETTER_QUEUE_METRICS.items():
            fn_result = metric_context["fn"](0)  # type: ignore
            metric = {
                "key": key,
                "value": metric_context.get("value"),
                "metric": metric_context.get("metric"),
                **fn_result,
            }
            output.append(metric)
        return output

    def get_object(self) -> DeadLetterQueueMetric:
        offset = 0
        try:
            offset = int(self.request.GET.get("offset") or 0)
        except:
            pass

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        key = self.kwargs[lookup_url_kwarg]
        return get_dlq_metric(key, offset)


def get_dead_letter_queue_size() -> int:
    return sync_execute("SELECT count(*) FROM events_dead_letter_queue")[0][0]


def get_dlq_last_error_timestamp() -> int:
    ts = sync_execute("SELECT max(error_timestamp) FROM events_dead_letter_queue")[0][0]

    last_error_timestamp = "-" if ts.timestamp() == datetime(1970, 1, 1).timestamp() else ts
    return last_error_timestamp


def get_dead_letter_queue_events_last_24h() -> int:
    return sync_execute(
        "SELECT count() FROM events_dead_letter_queue WHERE error_timestamp >= (NOW() - INTERVAL 1 DAY)"
    )[0][0]


def get_dead_letter_queue_events_per_error(offset: Optional[int] = 0) -> List[Union[str, int]]:
    return sync_execute(
        f"""
        SELECT error, count(*) AS c
        FROM events_dead_letter_queue
        GROUP BY error
        ORDER BY c DESC, error DESC
        LIMIT {ROWS_LIMIT}
        OFFSET {offset}
        """
    )


def get_dead_letter_queue_events_per_location(offset: Optional[int] = 0) -> List[Union[str, int]]:
    return sync_execute(
        f"""
        SELECT error_location, count(*) AS c
        FROM events_dead_letter_queue
        GROUP BY error_location
        ORDER BY c DESC, error_location DESC
        LIMIT {ROWS_LIMIT}
        OFFSET {offset}
        """
    )


def get_dead_letter_queue_events_per_day(offset: Optional[int] = 0) -> List[Union[str, int]]:
    return sync_execute(
        f"""
        SELECT toDate(error_timestamp) as day, count(*) AS c
        FROM events_dead_letter_queue
        GROUP BY day
        ORDER BY c DESC, day DESC
        LIMIT {ROWS_LIMIT}
        OFFSET {offset}
        """
    )


def get_dead_letter_queue_events_per_tag(offset: Optional[int] = 0) -> List[Union[str, int]]:
    return sync_execute(
        f"""
        SELECT arrayJoin(tags) as tag, count(*) as c from events_dead_letter_queue
        GROUP BY tag
        ORDER BY c DESC, tag DESC
        LIMIT {ROWS_LIMIT}
        OFFSET {offset}
        """
    )
