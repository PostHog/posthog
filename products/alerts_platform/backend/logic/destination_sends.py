"""What was sent to a destination lately, read from the log lines both delivery paths write.

A native send writes one line per message (`delivery/telemetry.py`). A HogFunction send writes
several per invocation, so an invocation is one send: failed when any line is an error, sent when
the function completed, and left out while it is neither, because it is still running.
"""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Final

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.alerts_platform.backend.delivery.telemetry import NATIVE_SEND_LOG_SOURCE
from products.alerts_platform.backend.facade.contracts import DestinationSend
from products.alerts_platform.backend.facade.enums import DeliveryPath

# Bounds the read to the hot tier of `log_entries`, the same window its logs endpoint uses.
LOOKBACK: Final = timedelta(days=7)
_HOG_FUNCTION_LOG_SOURCE: Final = "hog_function"
_HOG_FUNCTION_COMPLETED_PREFIX: Final = "Function completed"

_NATIVE_SENDS_SQL: Final = """
SELECT log_source_id, timestamp, upper(level) = 'ERROR', message
FROM log_entries
WHERE team_id = %(team_id)s
  AND log_source = %(log_source)s
  AND log_source_id IN %(destination_ids)s
  AND timestamp > %(after)s
ORDER BY timestamp DESC
LIMIT %(limit)s
"""

_HOG_FUNCTION_SENDS_SQL: Final = """
SELECT
    log_source_id,
    min(timestamp) AS sent_at,
    countIf(upper(level) = 'ERROR') > 0 AS failed,
    countIf(startsWith(message, %(completed_prefix)s)) > 0 AS completed,
    argMinIf(message, timestamp, upper(level) = 'ERROR') AS error
FROM log_entries
WHERE team_id = %(team_id)s
  AND log_source = %(log_source)s
  AND log_source_id IN %(destination_ids)s
  AND timestamp > %(after)s
GROUP BY log_source_id, instance_id
HAVING failed OR completed
ORDER BY sent_at DESC
LIMIT %(limit)s
"""


def recent_destination_sends(
    *, team_id: int, destination_ids: Collection[str], limit: int
) -> tuple[DestinationSend, ...]:
    if not destination_ids:
        return ()
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    args = {
        "team_id": team_id,
        "destination_ids": list(destination_ids),
        "after": (datetime.now(UTC) - LOOKBACK).strftime("%Y-%m-%d %H:%M:%S"),
        "limit": limit,
    }
    native = [
        DestinationSend(
            destination_id=destination_id,
            sent_at=_utc(sent_at),
            path=DeliveryPath.NATIVE,
            succeeded=not failed,
            error=message if failed else None,
        )
        for destination_id, sent_at, failed, message in sync_execute(
            _NATIVE_SENDS_SQL, {**args, "log_source": NATIVE_SEND_LOG_SOURCE}
        )
    ]
    hog_function = [
        DestinationSend(
            destination_id=destination_id,
            sent_at=_utc(sent_at),
            path=DeliveryPath.HOG_FUNCTION,
            succeeded=not failed,
            error=error if failed else None,
        )
        for destination_id, sent_at, failed, _completed, error in sync_execute(
            _HOG_FUNCTION_SENDS_SQL,
            {**args, "log_source": _HOG_FUNCTION_LOG_SOURCE, "completed_prefix": _HOG_FUNCTION_COMPLETED_PREFIX},
        )
    ]
    return tuple(sorted([*native, *hog_function], key=lambda send: send.sent_at, reverse=True)[:limit])


def _utc(timestamp: datetime) -> datetime:
    return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
