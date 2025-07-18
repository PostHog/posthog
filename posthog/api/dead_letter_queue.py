import datetime as dt
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

from rest_framework import mixins, permissions, serializers, viewsets

from posthog.clickhouse.client import sync_execute
from posthog.permissions import IsStaffUser
from posthog.utils import relative_date_parse

# keep in sync with posthog/frontend/src/scenes/instance/DeadLetterQueue/MetricsTab.tsx
ROWS_LIMIT = 10

DEAD_LETTER_QUEUE_METRICS = {
    "dlq_size": {
        "metric": "Total events in dead letter queue (in time range)",
        "fn": lambda offset, after_datetime, before_datetime: {
            "value": get_dead_letter_queue_size(offset, after_datetime, before_datetime)
        },
    },
    "dlq_last_error_timestamp": {
        "metric": "Last error timestamp",
        "fn": lambda offset, after_datetime, before_datetime: {
            "value": get_dlq_last_error_timestamp(offset, after_datetime, before_datetime)
        },
    },
    "dlq_events_per_error": {
        "metric": "Total events per error",
        "fn": lambda offset, after_datetime, before_datetime: {
            "subrows": {
                "columns": ["Error", "Total events"],
                "rows": get_dead_letter_queue_events_per_error(offset, after_datetime, before_datetime),
            }
        },
    },
    "dlq_events_per_location": {
        "metric": "Total events per error location",
        "fn": lambda offset, after_datetime, before_datetime: {
            "subrows": {
                "columns": ["Error location", "Total events"],
                "rows": get_dead_letter_queue_events_per_location(offset, after_datetime, before_datetime),
            }
        },
    },
    "dlq_events_per_day": {
        "metric": "Total events per day",
        "fn": lambda offset, after_datetime, before_datetime: {
            "subrows": {
                "columns": ["Date", "Total events"],
                "rows": get_dead_letter_queue_events_per_day(offset, after_datetime, before_datetime),
            }
        },
    },
    "dlq_events_per_tag": {
        "metric": "Total events per tag",
        "fn": lambda offset, after_datetime, before_datetime: {
            "subrows": {
                "columns": ["Date", "Total events"],
                "rows": get_dead_letter_queue_events_per_tag(offset, after_datetime, before_datetime),
            }
        },
    },
    "dlq_events": {
        "metric": "Events List",
        "fn": lambda offset, after_datetime, before_datetime: {
            "subrows": {
                "columns": [
                    "ID",
                    "Event UUID",
                    "Event",
                    "Properties",
                    "Distinct ID",
                    "Team ID",
                    "Elements Chain",
                    "Created At",
                    "IP",
                    "Site URL",
                    "Now",
                    "Raw Payload",
                    "Error Timestamp",
                    "Error Location",
                    "Error",
                    "Tags",
                    "Timestamp",
                    "Offset",
                ],
                "rows": get_dead_letter_queue_events(offset, after_datetime, before_datetime),
            }
        },
    },
}


class DeadLetterQueueMetric:
    key: str = ""
    metric: str = ""
    value: Union[str, bool, int, None] = None
    subrows: Optional[list[Any]] = None

    def __init__(self, **kwargs):
        for field in ("key", "metric", "value", "subrows"):
            setattr(self, field, kwargs.get(field, None))


def get_dlq_metric(
    key: str, offset: int, after_datetime: dt.datetime, before_datetime: dt.datetime
) -> DeadLetterQueueMetric:
    metric_context = DEAD_LETTER_QUEUE_METRICS[key]
    fn_result = metric_context["fn"](offset, after_datetime, before_datetime)  # type: ignore

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

    def get_queryset(self, *args, **kwargs):
        output = []
        after = self.request.GET.get("after", "-7d")
        before = self.request.GET.get("before", None)
        after_datetime = relative_date_parse(after, ZoneInfo("UTC"))
        before_datetime = relative_date_parse(before, ZoneInfo("UTC")) if before else dt.datetime.now(ZoneInfo("UTC"))
        for key, metric_context in DEAD_LETTER_QUEUE_METRICS.items():
            fn_result = metric_context["fn"](0, after_datetime, before_datetime)  # type: ignore
            metric = {
                "key": key,
                "value": metric_context.get("value"),
                "metric": metric_context.get("metric"),
                **fn_result,
            }
            output.append(metric)
        return output

    def get_object(self) -> DeadLetterQueueMetric:
        offset = int(self.request.GET.get("offset", "0"))
        after = self.request.GET.get("after", "-7d")
        before = self.request.GET.get("before", None)
        after_datetime = relative_date_parse(after, ZoneInfo("UTC"))
        before_datetime = relative_date_parse(before, ZoneInfo("UTC")) if before else dt.datetime.now(ZoneInfo("UTC"))

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        key = self.kwargs[lookup_url_kwarg]
        return get_dlq_metric(key, offset, after_datetime, before_datetime)


def get_dead_letter_queue_size(offset, after_datetime, before_datetime) -> int:
    return sync_execute(
        "SELECT count(*) FROM events_dead_letter_queue WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s",
        {"start": after_datetime, "end": before_datetime},
    )[0][0]


def get_dlq_last_error_timestamp(offset, after_datetime, before_datetime) -> int:
    ts = sync_execute(
        "SELECT max(error_timestamp) FROM events_dead_letter_queue WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s",
        {"start": after_datetime, "end": before_datetime},
    )[0][0]

    last_error_timestamp = "-" if ts.timestamp() == dt.datetime(1970, 1, 1).timestamp() else ts
    return last_error_timestamp


def get_dead_letter_queue_events(offset, after_datetime, before_datetime) -> list[dict[str, Any]]:
    return sync_execute(
        """
        SELECT
            id,
            event_uuid,
            event,
            properties,
            distinct_id,
            team_id,
            elements_chain,
            created_at,
            ip,
            site_url,
            now,
            raw_payload,
            error_timestamp,
            error_location,
            error,
            tags,
            _timestamp,
            _offset
        FROM events_dead_letter_queue
        WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s
        ORDER BY error_timestamp DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """,
        {"start": after_datetime, "end": before_datetime, "limit": ROWS_LIMIT, "offset": offset},
    )


def get_dead_letter_queue_events_per_error(offset, after_datetime, before_datetime) -> list[Union[str, int]]:
    return sync_execute(
        """
        SELECT error, count(*) AS c
        FROM events_dead_letter_queue
        WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s
        GROUP BY error
        ORDER BY c DESC, error DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """,
        {"start": after_datetime, "end": before_datetime, "limit": ROWS_LIMIT, "offset": offset},
    )


def get_dead_letter_queue_events_per_location(offset, after_datetime, before_datetime) -> list[Union[str, int]]:
    return sync_execute(
        """
        SELECT error_location, count(*) AS c
        FROM events_dead_letter_queue
        WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s
        GROUP BY error_location
        ORDER BY c DESC, error_location DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """,
        {"start": after_datetime, "end": before_datetime, "limit": ROWS_LIMIT, "offset": offset},
    )


def get_dead_letter_queue_events_per_day(offset, after_datetime, before_datetime) -> list[Union[str, int]]:
    return sync_execute(
        """
        SELECT toDate(error_timestamp) as day, count(*) AS c
        FROM events_dead_letter_queue
        WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s
        GROUP BY day
        ORDER BY c DESC, day DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """,
        {"start": after_datetime, "end": before_datetime, "limit": ROWS_LIMIT, "offset": offset},
    )


def get_dead_letter_queue_events_per_tag(offset, after_datetime, before_datetime) -> list[Union[str, int]]:
    return sync_execute(
        """
        SELECT arrayJoin(tags) as tag, count(*) as c from events_dead_letter_queue
        WHERE error_timestamp >= %(start)s AND error_timestamp <= %(end)s
        GROUP BY tag
        ORDER BY c DESC, tag DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """,
        {"start": after_datetime, "end": before_datetime, "limit": ROWS_LIMIT, "offset": offset},
    )
