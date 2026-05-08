"""Preagg-table versions of the heavy event-count usage-report queries.

These read from `usage_report_events_preagg` — a daily aggregate
materialized view fed off `KAFKA_EVENTS_JSON` — instead of the raw
`events` table. The legacy versions in `posthog/tasks/usage_report.py`
scan billions of rows and routinely take 10–20 minutes per run; the
preagg versions read tens-to-hundreds of pre-aggregated rows per
`(date, team_id)` and complete in seconds.

**Single-day only.** The usage-report workflow runs daily for the
previous calendar day (`get_previous_day` → start-of-day to
end-of-day, both within the same date), so these helpers filter on
``date = toDate(begin)`` and ignore ``end``. The legacy signatures
accept ``(begin, end)``, so we keep both args for parity, but the
preagg versions are documented as single-day only — multi-day callers
would silently get only the begin day.

The preagg keeps a 14-day TTL; the workflow's previous-day window is
well inside it.

Equivalence to the legacy versions:

* ``get_teams_with_billable_event_count_in_period_from_preagg`` — same
  excluded-events filter and the same
  ``count(distinct event, cityHash64(distinct_id), cityHash64(uuid))``
  math (no ``toDate(timestamp)`` term needed since we're already on a
  single date), computed via ``uniqExactMerge`` per ``team_id``.
* ``get_teams_with_billable_enhanced_persons_event_count_in_period_from_preagg``
  — same as above, additionally restricted to
  ``person_mode IN ('full', 'force_upgrade')``.
* ``get_all_event_metrics_in_period_from_preagg`` — same SDK-bucketing
  ``multiIf`` as the legacy version, but reads the materialized ``lib``
  column directly instead of parsing ``properties.$lib`` per row.

Note on hashing: the legacy query hashes ``cityHash64(uuid)`` directly
on the UUID column, while the MV stores
``cityHash64(toString(uuid))``. The hash values differ but the
distinctness property is preserved, so the resulting counts match.
"""

from collections.abc import Sequence
from datetime import datetime

from retry import retry

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.logging.timing import timed_log
from posthog.models.usage_report_events_preagg.sql import USAGE_REPORT_EVENTS_PREAGG_TABLE
from posthog.tasks.usage_report import (
    BILLABLE_EXCLUDED_EVENTS,
    CH_BILLING_SETTINGS,
    QUERY_RETRIES,
    QUERY_RETRY_BACKOFF,
    QUERY_RETRY_DELAY,
)

# Source-key list for the multi-output `all_event_metrics` spec. Order
# is irrelevant; the dict keys are looked up by name.
_ALL_EVENT_METRIC_KEYS: tuple[str, ...] = (
    "helicone_events",
    "langfuse_events",
    "keywords_ai_events",
    "traceloop_events",
    "web_events",
    "web_lite_events",
    "node_events",
    "android_events",
    "flutter_events",
    "ios_events",
    "go_events",
    "java_events",
    "react_native_events",
    "ruby_events",
    "python_events",
    "php_events",
    "dotnet_events",
    "elixir_events",
    "unity_events",
    "rust_events",
)


def _billable_count_query(extra_where: str = "") -> str:
    # Usage reports run daily for the previous calendar day, so we filter
    # to a single date. `end` is accepted for API parity with the legacy
    # signature but unused here — the helper is documented as single-day
    # only.
    return f"""
        SELECT team_id, toUInt64(uniqExactMerge(distinct_events_unique)) AS count
        FROM {USAGE_REPORT_EVENTS_PREAGG_TABLE}
        WHERE date = toDate(%(begin)s)
            AND event NOT IN %(excluded_events)s
            {extra_where}
        GROUP BY team_id
    """


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_billable_event_count_in_period_from_preagg(
    begin: datetime, end: datetime
) -> Sequence[tuple[int, int]]:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
        return sync_execute(
            _billable_count_query(),
            {"begin": begin, "end": end, "excluded_events": BILLABLE_EXCLUDED_EVENTS},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_billable_enhanced_persons_event_count_in_period_from_preagg(
    begin: datetime, end: datetime
) -> Sequence[tuple[int, int]]:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
        return sync_execute(
            _billable_count_query("AND person_mode IN ('full', 'force_upgrade')"),
            {"begin": begin, "end": end, "excluded_events": BILLABLE_EXCLUDED_EVENTS},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_all_event_metrics_in_period_from_preagg(begin: datetime, end: datetime) -> dict[str, list[tuple[int, int]]]:
    # `lib` is a materialized column on the preagg, so unlike the legacy
    # version we don't need `get_property_string_expr` to dig $lib out
    # of `properties` per row.
    query = f"""
        SELECT
            team_id,
            multiIf(
                event LIKE 'helicone%%', 'helicone_events',
                event LIKE 'langfuse%%', 'langfuse_events',
                event LIKE 'keywords_ai%%', 'keywords_ai_events',
                event LIKE 'traceloop%%', 'traceloop_events',
                lib = 'web', 'web_events',
                lib = 'js', 'web_lite_events',
                lib = 'posthog-node', 'node_events',
                lib = 'posthog-android', 'android_events',
                lib = 'posthog-flutter', 'flutter_events',
                lib = 'posthog-ios', 'ios_events',
                lib = 'posthog-go', 'go_events',
                lib = 'posthog-java', 'java_events',
                lib = 'posthog-server', 'java_events',
                lib = 'posthog-react-native', 'react_native_events',
                lib = 'posthog-ruby', 'ruby_events',
                lib = 'posthog-python', 'python_events',
                lib = 'posthog-php', 'php_events',
                lib = 'posthog-dotnet', 'dotnet_events',
                lib = 'posthog-elixir', 'elixir_events',
                lib = 'posthog-unity', 'unity_events',
                lib = 'posthog-rs', 'rust_events',
                'other'
            ) AS metric,
            toUInt64(sumMerge(event_count)) AS count
        FROM {USAGE_REPORT_EVENTS_PREAGG_TABLE}
        WHERE date = toDate(%(begin)s)
        GROUP BY team_id, metric
        HAVING metric != 'other'
    """

    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.USAGE_REPORT):
        rows = sync_execute(
            query,
            {"begin": begin, "end": end},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )

    out: dict[str, list[tuple[int, int]]] = {key: [] for key in _ALL_EVENT_METRIC_KEYS}
    for team_id, metric, count in rows:
        bucket = out.get(metric)
        if bucket is not None:
            bucket.append((int(team_id), int(count)))
    return out
