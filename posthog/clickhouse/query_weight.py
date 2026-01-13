from enum import Enum

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser


class QueryWeight(Enum):
    UNSUPPORTED = "unsupported"  # Entity type not supported for weight checking
    UNDECISIVE = "undecisive"  # No historical data
    NORMAL = "normal"  # Historical data exists, not heavy
    HEAVY = "heavy"  # Historical data shows heavy execution


# Thresholds
HEAVY_READ_BYTES = 1_000_000_000_000  # 1TB
HEAVY_DURATION_MS = 300_000  # 300 seconds
HEAVY_EXCEPTION_CODES = (241, 159)  # MEMORY_LIMIT_EXCEEDED, TIMEOUT_EXCEEDED


def get_query_weight(
    *,
    team_id: int,
    cohort_id: int | None = None,
    experiment_id: int | None = None,
    insight_id: int | None = None,
) -> QueryWeight:
    """
    Determine if a query is likely to be heavy based on historical execution.

    Checks the last 7 days of query_log_archive for matching queries.
    Returns UNDECISIVE if no history or on error, HEAVY if any execution exceeded thresholds,
    NORMAL otherwise.
    """
    if cohort_id is not None:
        filter_clause = "lc_cohort_id = %(entity_id)s"
        entity_id = cohort_id
    elif experiment_id is not None:
        filter_clause = "lc_experiment_id = %(entity_id)s"
        entity_id = experiment_id
    elif insight_id is not None:
        filter_clause = "lc_insight_id = %(entity_id)s"
        entity_id = insight_id
    else:
        return QueryWeight.UNSUPPORTED

    query = f"""
        SELECT
            count() as total_queries,
            countIf(
                exception_code IN %(heavy_exception_codes)s
                OR read_bytes > %(heavy_read_bytes)s
                OR query_duration_ms > %(heavy_duration_ms)s
            ) as heavy_queries
        FROM query_log_archive
        WHERE team_id = %(team_id)s
          AND {filter_clause}
          AND event_date >= today() - 7
          AND type = 'QueryFinish'
    """

    try:
        result = sync_execute(
            query,
            {
                "team_id": team_id,
                "entity_id": entity_id,
                "heavy_exception_codes": HEAVY_EXCEPTION_CODES,
                "heavy_read_bytes": HEAVY_READ_BYTES,
                "heavy_duration_ms": HEAVY_DURATION_MS,
            },
            ch_user=ClickHouseUser.META,
        )
    except Exception:
        return QueryWeight.UNDECISIVE

    if not result or result[0][0] == 0:
        return QueryWeight.UNDECISIVE

    total_queries, heavy_queries = result[0]
    return QueryWeight.HEAVY if heavy_queries > 0 else QueryWeight.NORMAL
