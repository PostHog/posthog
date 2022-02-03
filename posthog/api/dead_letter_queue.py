from datetime import datetime
from typing import Any, Dict, List, Union

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.client import sync_execute
from posthog.permissions import IsStaffUser
from posthog.version import VERSION


class DeadLetterQueueViewSet(viewsets.ViewSet):
    """
    Show info about instance for this user
    """

    permission_classes = [IsStaffUser]

    def list(self, request: Request) -> Response:

        metrics: List[Dict[str, Union[str, bool, int, float, Dict[str, Any]]]] = []

        metrics.append(
            {"key": "dlq_size", "metric": "Total events in dead letter queue", "value": get_dead_letter_queue_size()}
        )

        metrics.append(
            {
                "key": "dlq_events_last_24h",
                "metric": "Events sent to dead letter queue in the last 24h",
                "value": get_dead_letter_queue_events_last_24h(),
            }
        )

        metrics.append(
            {
                "key": "dlq_last_error_timestamp",
                "metric": "Last error timestamp",
                "value": get_dlq_last_error_timestamp(),
            }
        )

        metrics.append(
            {
                "key": "dlq_events_per_error",
                "metric": "Total events per error",
                "value": "",
                "subrows": {"columns": ["Error", "Total events"], "rows": get_dead_letter_queue_events_per_error()},
            }
        )

        metrics.append(
            {
                "key": "dlq_events_per_location",
                "metric": "Total events per error location",
                "value": "",
                "subrows": {
                    "columns": ["Error location", "Total events"],
                    "rows": get_dead_letter_queue_events_per_location(),
                },
            }
        )

        metrics.append(
            {
                "key": "dlq_events_per_day",
                "metric": "Total events per day",
                "value": "",
                "subrows": {"columns": ["Date", "Total events"], "rows": get_dead_letter_queue_events_per_day()},
            }
        )

        return Response({"results": {"overview": metrics}})


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
