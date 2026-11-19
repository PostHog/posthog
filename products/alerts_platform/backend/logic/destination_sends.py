"""What was sent to a destination lately, read from the log lines both delivery paths write.

A native send writes one line per message (`delivery/telemetry.py`). A HogFunction send writes
several per invocation, so an invocation is one send. It is sent once the function completed, and
failed on an error that no retry follows. A failed fetch that retries logs an error ending in
"Retrying." under the same invocation, so such a line is not an outcome. An invocation with
neither is still running and is left out.

Only a native failure carries its reason. A HogFunction's log lines can quote its inputs, a
credential-bearing webhook URL among them, and reading them needs `hog_function:read`, so its
failures carry no text here.
"""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Final

from posthog.api.log_entries import LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.event.util import format_clickhouse_timestamp

from products.alerts_platform.backend.delivery.telemetry import NATIVE_SEND_LOG_SOURCE
from products.alerts_platform.backend.facade.contracts import DestinationSend
from products.alerts_platform.backend.facade.enums import DeliveryPath

_HOG_FUNCTION_LOG_SOURCE: Final = "hog_function"
_HOG_FUNCTION_COMPLETED_PREFIX: Final = "Function completed"
_HOG_FUNCTION_RETRY_SUFFIX: Final = "Retrying."

_SENDS_SQL: Final = """
SELECT destination_id, sent_at, path, failed, error
FROM (
    SELECT log_source_id AS destination_id, timestamp AS sent_at, %(native_path)s AS path,
        upper(level) = 'ERROR' AS failed, message AS error
    FROM log_entries
    WHERE team_id = %(team_id)s
      AND log_source = %(native_source)s
      AND log_source_id IN %(destination_ids)s
      AND timestamp > %(after)s

    UNION ALL

    SELECT log_source_id AS destination_id, min(timestamp) AS sent_at, %(hog_function_path)s AS path,
        countIf(startsWith(message, %(completed_prefix)s)) = 0 AS failed,
        '' AS error
    FROM log_entries
    WHERE team_id = %(team_id)s
      AND log_source = %(hog_function_source)s
      AND log_source_id IN %(destination_ids)s
      AND timestamp > %(after)s
    GROUP BY log_source_id, instance_id
    HAVING NOT failed OR countIf(upper(level) = 'ERROR' AND NOT endsWith(message, %(retry_suffix)s)) > 0
)
ORDER BY sent_at DESC
LIMIT %(limit)s
"""


def recent_destination_sends(
    *, team_id: int, destination_ids: Collection[str], limit: int
) -> tuple[DestinationSend, ...]:
    if not destination_ids:
        return ()
    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = sync_execute(
        _SENDS_SQL,
        {
            "team_id": team_id,
            "destination_ids": list(destination_ids),
            # Bounds the read to the hot tier of `log_entries`, the same window its logs endpoint uses.
            "after": format_clickhouse_timestamp(datetime.now(UTC) - timedelta(days=LOG_ENTRIES_DEFAULT_LOOKBACK_DAYS)),
            "limit": limit,
            "native_source": NATIVE_SEND_LOG_SOURCE,
            "native_path": DeliveryPath.NATIVE.value,
            "hog_function_source": _HOG_FUNCTION_LOG_SOURCE,
            "hog_function_path": DeliveryPath.HOG_FUNCTION.value,
            "completed_prefix": _HOG_FUNCTION_COMPLETED_PREFIX,
            "retry_suffix": _HOG_FUNCTION_RETRY_SUFFIX,
        },
    )
    return tuple(
        DestinationSend(
            destination_id=destination_id,
            sent_at=sent_at if sent_at.tzinfo is not None else sent_at.replace(tzinfo=UTC),
            path=DeliveryPath(path),
            succeeded=not failed,
            error=error if failed and error else None,
        )
        for destination_id, sent_at, path, failed, error in rows
    )
