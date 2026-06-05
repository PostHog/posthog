from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal, Optional, cast

from django.conf import settings

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.usage_report_events_preagg.sql import (
    USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE,
    USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL,
    USAGE_REPORT_EVENTS_HAS_GROUP_EXPRESSION,
    USAGE_REPORT_EVENTS_LATEST_BUCKET_VERSIONS_CTE_SQL,
    USAGE_REPORT_EVENTS_LIB_EXPRESSION,
    USAGE_REPORT_EVENTS_PREAGGREGATION_BOUNDS_SQL,
)
from posthog.tasks.usage_report import (
    AI_EVENTS,
    CH_BILLING_SETTINGS,
    get_all_event_metrics_in_period as _legacy_get_all_event_metrics_in_period,
    get_teams_with_billable_enhanced_persons_event_count_in_period as _legacy_get_enhanced_persons_count,
    get_teams_with_billable_event_count_in_period as _legacy_get_billable_event_count,
    get_teams_with_event_count_with_groups_in_period as _legacy_get_event_count_with_groups,
)

logger = structlog.get_logger(__name__)

TeamCountRows = list[tuple[int, int]]
EventMetricRows = list[tuple[int, str, int]]
EventMetricsResult = dict[str, TeamCountRows]

USAGE_REPORT_EVENTS_PREAGGREGATION_MAX_STALENESS = timedelta(minutes=30)
USAGE_REPORT_EVENTS_PREAGGREGATION_TAIL_MAX_AGE = timedelta(days=6)
USAGE_REPORT_EVENTS_PREAGGREGATION_SETTING = "USE_USAGE_REPORT_EVENTS_PREAGGREGATION"

EVENT_METRIC_KEYS = [
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
]

EVENT_METRIC_EXPRESSION = """
multiIf(
    event LIKE 'helicone%%', 'helicone_events',
    event LIKE 'langfuse%%', 'langfuse_events',
    event LIKE 'keywords_ai%%', 'keywords_ai_events',
    event LIKE 'traceloop%%', 'traceloop_events',
    {lib_expression} = 'web', 'web_events',
    {lib_expression} = 'js', 'web_lite_events',
    {lib_expression} = 'posthog-node', 'node_events',
    {lib_expression} = 'posthog-android', 'android_events',
    {lib_expression} = 'posthog-flutter', 'flutter_events',
    {lib_expression} = 'posthog-ios', 'ios_events',
    {lib_expression} = 'posthog-go', 'go_events',
    {lib_expression} = 'posthog-java', 'java_events',
    {lib_expression} = 'posthog-server', 'java_events',
    {lib_expression} = 'posthog-react-native', 'react_native_events',
    {lib_expression} = 'posthog-ruby', 'ruby_events',
    {lib_expression} = 'posthog-python', 'python_events',
    {lib_expression} = 'posthog-php', 'php_events',
    {lib_expression} = 'posthog-dotnet', 'dotnet_events',
    {lib_expression} = 'posthog-elixir', 'elixir_events',
    {lib_expression} = 'posthog-unity', 'unity_events',
    {lib_expression} = 'posthog-rs', 'rust_events',
    'other'
)
""".strip()


def _combine_team_count_results(results_list: list[TeamCountRows]) -> TeamCountRows:
    team_counts: defaultdict[int, int] = defaultdict(int)
    for results in results_list:
        for team_id, count in results:
            team_counts[team_id] += count

    return list(team_counts.items())


def _combine_event_metrics_results(results_list: list[EventMetricRows]) -> EventMetricsResult:
    metrics: dict[str, dict[int, int]] = {metric: {} for metric in EVENT_METRIC_KEYS}

    for results in results_list:
        for team_id, metric, count in results:
            if metric in metrics:
                metrics[metric][team_id] = metrics[metric].get(team_id, 0) + count

    return {metric: list(team_counts.items()) for metric, team_counts in metrics.items()}


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_usage_report_events_preaggregation_enabled() -> bool:
    return bool(getattr(settings, USAGE_REPORT_EVENTS_PREAGGREGATION_SETTING, False))


def _is_whole_utc_day_range(begin: datetime, end: datetime) -> bool:
    begin_utc = _to_utc(begin)
    end_utc = _to_utc(end)
    return (
        begin_utc < end_utc
        and begin_utc.hour == 0
        and begin_utc.minute == 0
        and begin_utc.second == 0
        and begin_utc.microsecond == 0
        and end_utc.hour == 0
        and end_utc.minute == 0
        and end_utc.second == 0
        and end_utc.microsecond == 0
    )


def _get_usage_report_events_preaggregation_max_bucket_end(begin: datetime, end: datetime) -> Optional[datetime]:
    if not _is_usage_report_events_preaggregation_enabled():
        return None

    if _to_utc(end) < datetime.now(UTC) - USAGE_REPORT_EVENTS_PREAGGREGATION_TAIL_MAX_AGE:
        return None

    try:
        rows = sync_execute(
            USAGE_REPORT_EVENTS_PREAGGREGATION_BOUNDS_SQL(),
            {"begin": begin, "end": end},
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
            ch_user=ClickHouseUser.BILLING,
        )
    except Exception:
        logger.warning("usage_report_events_preaggregation.bounds_failed", exc_info=True)
        return None

    if not rows or rows[0][0] is None or rows[0][1] is None:
        return None

    min_bucket_start = _to_utc(rows[0][0])
    max_bucket_end = _to_utc(rows[0][1])

    if min_bucket_start > _to_utc(begin):
        return None

    if (
        max_bucket_end < _to_utc(end)
        and max_bucket_end < datetime.now(UTC) - USAGE_REPORT_EVENTS_PREAGGREGATION_MAX_STALENESS
    ):
        return None

    return max_bucket_end


def _get_excluded_billable_events() -> list[str]:
    return [
        "$feature_flag_called",
        "survey sent",
        "survey shown",
        "survey dismissed",
        "$exception",
        *AI_EVENTS,
    ]


def _get_teams_with_billable_event_count_from_preaggregation(
    begin: datetime,
    end: datetime,
    *,
    usage_kind: Literal["all", "enhanced_persons"],
    count_distinct: bool,
) -> Optional[TeamCountRows]:
    # Exact distinct counts are not composable by summing 15-minute bucket
    # uniques, because duplicate event UUIDs can land in different inserted_at
    # buckets. Keep those reads on the raw events path until we store a safely
    # mergeable range-level dedup state.
    if count_distinct:
        return None

    if not _is_whole_utc_day_range(begin, end):
        return None

    with tags_context(
        product=Product.PRODUCT_ANALYTICS,
        feature=Feature.USAGE_REPORT,
        usage_report="events_preaggregation_read",
    ):
        max_bucket_end = _get_usage_report_events_preaggregation_max_bucket_end(begin, end)
        if max_bucket_end is None:
            return None

        excluded_events = _get_excluded_billable_events()
        person_mode_clause = "AND person_mode IN ('full', 'force_upgrade')" if usage_kind == "enhanced_persons" else ""

        try:
            preaggregated_rows = cast(
                TeamCountRows,
                sync_execute(
                    USAGE_REPORT_EVENTS_DEDUP_PREAGGREGATED_READ_SQL("raw_count"),
                    {
                        "begin": begin,
                        "end": end,
                        "max_bucket_end": max_bucket_end,
                        "usage_kind": usage_kind,
                        "excluded_events": excluded_events,
                    },
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
            tail_rows = cast(
                TeamCountRows,
                sync_execute(
                    f"""
                    SELECT team_id, count(1) as count
                    FROM events_recent
                    WHERE timestamp >= %(begin)s AND timestamp < %(end)s
                        AND inserted_at >= %(max_bucket_end)s
                        AND event NOT IN %(excluded_events)s
                        {person_mode_clause}
                    GROUP BY team_id
                    """,
                    {
                        "begin": begin,
                        "end": end,
                        "max_bucket_end": max_bucket_end,
                        "excluded_events": excluded_events,
                    },
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
        except Exception:
            logger.warning("usage_report_events_preaggregation.billable_read_failed", exc_info=True)
            return None

    return _combine_team_count_results([preaggregated_rows, tail_rows])


def get_teams_with_billable_event_count_in_period(
    begin: datetime, end: datetime, count_distinct: bool = False
) -> TeamCountRows:
    preaggregated_result = _get_teams_with_billable_event_count_from_preaggregation(
        begin,
        end,
        usage_kind="all",
        count_distinct=count_distinct,
    )
    if preaggregated_result is not None:
        return preaggregated_result

    return _legacy_get_billable_event_count(begin, end, count_distinct=count_distinct)


def get_teams_with_billable_enhanced_persons_event_count_in_period(
    begin: datetime, end: datetime, count_distinct: bool = False
) -> TeamCountRows:
    preaggregated_result = _get_teams_with_billable_event_count_from_preaggregation(
        begin,
        end,
        usage_kind="enhanced_persons",
        count_distinct=count_distinct,
    )
    if preaggregated_result is not None:
        return preaggregated_result

    return _legacy_get_enhanced_persons_count(begin, end, count_distinct=count_distinct)


def get_teams_with_event_count_with_groups_in_period(begin: datetime, end: datetime) -> TeamCountRows:
    if not _is_whole_utc_day_range(begin, end):
        return _legacy_get_event_count_with_groups(begin, end)

    with tags_context(
        product=Product.GROUP_ANALYTICS,
        feature=Feature.USAGE_REPORT,
        usage_report="events_preaggregation_read",
    ):
        max_bucket_end = _get_usage_report_events_preaggregation_max_bucket_end(begin, end)
        if max_bucket_end is None:
            return _legacy_get_event_count_with_groups(begin, end)

        try:
            preaggregated_rows = cast(
                TeamCountRows,
                sync_execute(
                    f"""
                    WITH {USAGE_REPORT_EVENTS_LATEST_BUCKET_VERSIONS_CTE_SQL()}
                    SELECT team_id, sum(count) AS count
                    FROM
                    (
                        SELECT
                            c.date,
                            c.bucket_start,
                            c.team_id,
                            c.person_mode,
                            c.lib,
                            c.event,
                            c.has_group,
                            max(c.event_count) AS count
                        FROM {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE} c
                        INNER JOIN latest_bucket_versions
                            ON c.bucket_start = latest_bucket_versions.bucket_start
                           AND c.computed_at = latest_bucket_versions.computed_at
                        WHERE c.date >= toDate(%(begin)s)
                          AND c.date < toDate(%(end)s)
                          AND c.bucket_start < %(max_bucket_end)s
                          AND c.has_group = 1
                        GROUP BY c.date, c.bucket_start, c.team_id, c.person_mode, c.lib, c.event, c.has_group
                    )
                    GROUP BY team_id
                    """,
                    {"begin": begin, "end": end, "max_bucket_end": max_bucket_end},
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
            tail_rows = cast(
                TeamCountRows,
                sync_execute(
                    f"""
                    SELECT team_id, count(1) as count
                    FROM events_recent
                    WHERE timestamp >= %(begin)s AND timestamp < %(end)s
                        AND inserted_at >= %(max_bucket_end)s
                        AND ({USAGE_REPORT_EVENTS_HAS_GROUP_EXPRESSION})
                    GROUP BY team_id
                    """,
                    {"begin": begin, "end": end, "max_bucket_end": max_bucket_end},
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
        except Exception:
            logger.warning("usage_report_events_preaggregation.group_read_failed", exc_info=True)
            return _legacy_get_event_count_with_groups(begin, end)

    return _combine_team_count_results([preaggregated_rows, tail_rows])


def get_all_event_metrics_in_period(begin: datetime, end: datetime) -> EventMetricsResult:
    if not _is_whole_utc_day_range(begin, end):
        return _legacy_get_all_event_metrics_in_period(begin, end)

    with tags_context(
        product=Product.PRODUCT_ANALYTICS,
        feature=Feature.USAGE_REPORT,
        usage_report="events_preaggregation_read",
    ):
        max_bucket_end = _get_usage_report_events_preaggregation_max_bucket_end(begin, end)
        if max_bucket_end is None:
            return _legacy_get_all_event_metrics_in_period(begin, end)

        metric_expression = EVENT_METRIC_EXPRESSION.format(lib_expression="lib")
        tail_metric_expression = EVENT_METRIC_EXPRESSION.format(lib_expression=USAGE_REPORT_EVENTS_LIB_EXPRESSION)

        try:
            preaggregated_rows = cast(
                EventMetricRows,
                sync_execute(
                    f"""
                    WITH {USAGE_REPORT_EVENTS_LATEST_BUCKET_VERSIONS_CTE_SQL()}
                    SELECT team_id, {metric_expression} AS metric, sum(count) AS count
                    FROM
                    (
                        SELECT
                            c.date,
                            c.bucket_start,
                            c.team_id,
                            c.person_mode,
                            c.lib,
                            c.event,
                            c.has_group,
                            max(c.event_count) AS count
                        FROM {USAGE_REPORT_EVENTS_COUNT_PREAGGREGATED_TABLE} c
                        INNER JOIN latest_bucket_versions
                            ON c.bucket_start = latest_bucket_versions.bucket_start
                           AND c.computed_at = latest_bucket_versions.computed_at
                        WHERE c.date >= toDate(%(begin)s)
                          AND c.date < toDate(%(end)s)
                          AND c.bucket_start < %(max_bucket_end)s
                        GROUP BY c.date, c.bucket_start, c.team_id, c.person_mode, c.lib, c.event, c.has_group
                    )
                    GROUP BY team_id, metric
                    HAVING metric != 'other'
                    """,
                    {"begin": begin, "end": end, "max_bucket_end": max_bucket_end},
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
            tail_rows = cast(
                EventMetricRows,
                sync_execute(
                    f"""
                    SELECT
                        team_id,
                        {tail_metric_expression} AS metric,
                        count(1) AS count
                    FROM events_recent
                    WHERE timestamp >= %(begin)s AND timestamp < %(end)s
                      AND inserted_at >= %(max_bucket_end)s
                    GROUP BY team_id, metric
                    HAVING metric != 'other'
                    """,
                    {"begin": begin, "end": end, "max_bucket_end": max_bucket_end},
                    workload=Workload.OFFLINE,
                    settings=CH_BILLING_SETTINGS,
                    ch_user=ClickHouseUser.BILLING,
                ),
            )
        except Exception:
            logger.warning("usage_report_events_preaggregation.metrics_read_failed", exc_info=True)
            return _legacy_get_all_event_metrics_in_period(begin, end)

    return _combine_event_metrics_results([preaggregated_rows, tail_rows])
