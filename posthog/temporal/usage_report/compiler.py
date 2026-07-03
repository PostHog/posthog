"""Compile the metric catalog into fused ClickHouse queries.

One family = one scan: every `EventsMetric` becomes an `If`-combinator
aggregate in a single `GROUP BY team_id` query over `events`, instead of one
full table pass per metric. Deduplicated counts use `uniqExactIf` per time
split and are summed across splits — the same semantics as the legacy
`_execute_split_query(count_distinct=True)` path, where only duplicates
landing in the same split collapse.

Retries are intentionally absent: the Temporal activity running this owns the
retry policy.
"""

from datetime import datetime

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.temporal.usage_report.catalog import EVENTS_METRICS, EventsMetric

CH_BILLING_SETTINGS = {
    "max_execution_time": 5 * 60,
}

# Splitting the period bounds per-query memory; 12 matches the legacy event
# count queries so dedup-within-split behavior is identical.
NUM_SPLITS = 12

# Matches the merge-tree deduplication key for the events table:
# https://github.com/PostHog/posthog/blob/master/posthog/models/event/sql.py
DEDUP_KEY = "(toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))"


def compile_events_sql(metrics: tuple[EventsMetric, ...]) -> str:
    aggregates = ",\n            ".join(
        f"uniqExactIf({DEDUP_KEY}, {m.where.sql}) AS {m.name}" if m.dedup else f"countIf({m.where.sql}) AS {m.name}"
        for m in metrics
    )
    return f"""
        SELECT
            team_id,
            {aggregates}
        FROM events
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
    """


def run_events_family(begin: datetime, end: datetime) -> dict[str, list[tuple[int, int]]]:
    """Execute the fused events scan over the period, split into
    `NUM_SPLITS` time slices summed per team. Returns rows keyed by metric
    name, fanned out to `all_data` keys via the spec's `multi_keys_mapping`.
    """
    query = compile_events_sql(EVENTS_METRICS)
    totals: dict[str, dict[int, int]] = {m.name: {} for m in EVENTS_METRICS}
    split_delta = (end - begin) / NUM_SPLITS

    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
        for i in range(NUM_SPLITS):
            split_begin = begin + split_delta * i
            split_end = end if i == NUM_SPLITS - 1 else begin + split_delta * (i + 1)
            rows = sync_execute(
                query,
                {"begin": split_begin, "end": split_end},
                workload=Workload.OFFLINE,
                settings=CH_BILLING_SETTINGS,
                ch_user=ClickHouseUser.BILLING,
            )
            for team_id, *values in rows:
                for metric, value in zip(EVENTS_METRICS, values):
                    team_totals = totals[metric.name]
                    team_totals[team_id] = team_totals.get(team_id, 0) + value

    return {name: list(team_totals.items()) for name, team_totals in totals.items()}
