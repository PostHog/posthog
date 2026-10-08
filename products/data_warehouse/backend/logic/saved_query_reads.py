from datetime import datetime

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.warehouse_object_reads import WAREHOUSE_OBJECT_READS_DAILY_TABLE, ReadKind, SubjectKind
from posthog.exceptions_capture import capture_exception

MAX_EXECUTION_TIME_SECONDS = 5

LAST_READ_AT_SQL = f"""
SELECT toTimeZone(max(max_event_time), 'UTC')
FROM {WAREHOUSE_OBJECT_READS_DAILY_TABLE}
WHERE team_id = %(team_id)s
    AND read_kind = %(read_kind)s
    AND subject_kind = %(subject_kind)s
    AND subject_id = %(saved_query_id)s
HAVING count() > 0
"""


def last_read_at(team_id: int, saved_query_id: str) -> datetime | None:
    """When a query last read this saved query, by the daily read rollup, or None if unknown."""
    tag_queries(product=Product.WAREHOUSE, feature=Feature.DATA_MODELING)
    try:
        rows = sync_execute(
            LAST_READ_AT_SQL,
            {
                "team_id": team_id,
                "read_kind": ReadKind.READ.value,
                "subject_kind": SubjectKind.SAVED_QUERY.value,
                "saved_query_id": saved_query_id,
            },
            settings={"max_execution_time": MAX_EXECUTION_TIME_SECONDS},
            workload=Workload.OFFLINE,
        )
    except Exception as error:
        capture_exception(error)
        return None
    return rows[0][0] if rows else None
