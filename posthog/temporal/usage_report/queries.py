"""Registry of usage-report gathering queries.

Each `QuerySpec` describes one fetch — typically one ClickHouse query, one
Postgres aggregation, or one error-tracking API call — and how its result maps
back to keys in the legacy `_get_all_usage_data` dict that
`_get_team_report` consumes.

Most queries produce a single destination key (`output="single"`); a handful
already return a dict-of-keys in one query (`output="multi"`) and we keep
those as a single fetch to avoid re-running the same heavy ClickHouse pass
many times. The aggregation activity fans `multi` results back out into the
flat `all_data` shape the existing helpers expect.

⚠️  Snapshot queries — re-run safety disclaimer
-----------------------------------------------
Specs marked `kind="snapshot"` ignore the period (`begin`, `end`) and read
the *current* state of the database/storage at the moment they execute. This
is inherited from the existing Celery `_get_all_usage_data` behavior — names
like `teams_with_active_external_data_schemas_in_period` end in
`_in_period` for historical reasons, but the underlying queries do **not**
filter on the period.

Practical implications:

* Re-running the workflow for the same `period_start`/`period_end` will
  produce different snapshot numbers if the underlying state has changed
  (counts of dashboards, feature flags, surveys, active hog destinations,
  DWH storage in S3, error-tracking issue counts, etc.).
* These metrics are not strictly attributable to the report's date — they
  reflect "now" at the time the workflow runs.

Period queries (`kind="period"`) are re-run safe: they filter ClickHouse on
`timestamp >= begin AND timestamp < end`, so re-running for the same period
returns the same result (modulo data still being ingested into the period).

Until billing changes how it reads these metrics we keep the existing
behavior — see `posthog/tasks/usage_report.py:_get_all_usage_data` for the
canonical reference.
"""

import dataclasses
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from django.db.models import Count

from posthog.constants import FlagRequestType
from posthog.models import GroupTypeMapping
from posthog.models.feature_flag import FeatureFlag
from posthog.tasks.usage_report import (
    get_all_event_metrics_in_period,
    get_teams_with_active_batch_exports_in_period,
    get_teams_with_active_external_data_schemas_in_period,
    get_teams_with_active_hog_destinations_in_period,
    get_teams_with_active_hog_transformations_in_period,
    get_teams_with_ai_credits_used_in_period,
    get_teams_with_ai_event_count_in_period,
    get_teams_with_api_queries_metrics,
    get_teams_with_billable_enhanced_persons_event_count_in_period,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_cdp_billable_invocations_in_period,
    get_teams_with_dwh_mat_views_storage_in_s3,
    get_teams_with_dwh_tables_storage_in_s3,
    get_teams_with_dwh_total_storage_in_s3,
    get_teams_with_event_count_with_groups_in_period,
    get_teams_with_exceptions_captured_in_period,
    get_teams_with_feature_flag_requests_count_in_period,
    get_teams_with_free_historical_rows_synced_in_period,
    get_teams_with_hog_function_calls_in_period,
    get_teams_with_hog_function_fetch_calls_in_period,
    get_teams_with_logs_bytes_in_period,
    get_teams_with_logs_records_in_period,
    get_teams_with_mobile_billable_recording_count_in_period,
    get_teams_with_query_metric,
    get_teams_with_recording_bytes_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_rows_exported_in_period,
    get_teams_with_rows_synced_in_period,
    get_teams_with_survey_responses_count_in_period,
    get_teams_with_workflow_billable_invocations_in_period,
    get_teams_with_workflow_emails_sent_in_period,
    get_teams_with_workflow_push_sent_in_period,
    get_teams_with_workflow_sms_sent_in_period,
    get_teams_with_zero_duration_recording_count_in_period,
)

from products.dashboards.backend.models.dashboard import Dashboard
from products.error_tracking.backend.facade import api as error_tracking_api
from products.surveys.backend.models import Survey

# ---- Postgres ORM / API helpers ---------------------------------------------
# These are snapshot queries — they take no period args because they read
# the *current* state of the database at the moment they run.


def _group_types_total() -> list[dict[str, int]]:
    return list(
        GroupTypeMapping.objects.values("team_id")  # nosemgrep: no-direct-persons-db-orm
        .annotate(total=Count("id"))
        .order_by("team_id")  # nosemgrep: no-direct-persons-db-orm
    )


def _dashboard_count() -> list[dict[str, int]]:
    return list(Dashboard.objects.values("team_id").annotate(total=Count("id")).order_by("team_id"))


def _dashboard_template_count() -> list[dict[str, int]]:
    return list(
        Dashboard.objects.filter(creation_mode="template")
        .values("team_id")
        .annotate(total=Count("id"))
        .order_by("team_id")
    )


def _dashboard_shared_count() -> list[dict[str, int]]:
    return list(
        Dashboard.objects.filter(sharingconfiguration__enabled=True)
        .values("team_id")
        .annotate(total=Count("id"))
        .order_by("team_id")
    )


def _dashboard_tagged_count() -> list[dict[str, int]]:
    return list(
        Dashboard.objects.filter(tagged_items__isnull=False)
        .values("team_id")
        .annotate(total=Count("id"))
        .order_by("team_id")
    )


def _ff_count() -> list[dict[str, int]]:
    return list(FeatureFlag.objects.values("team_id").annotate(total=Count("id")).order_by("team_id"))


def _ff_active_count() -> list[dict[str, int]]:
    return list(
        FeatureFlag.objects.filter(active=True).values("team_id").annotate(total=Count("id")).order_by("team_id")
    )


def _survey_count() -> list[dict[str, int]]:
    return list(Survey.objects.values("team_id").annotate(total=Count("id")).order_by("team_id"))


def _issues_created_total() -> list[dict[str, int]]:
    return [{"team_id": team_id, "total": total} for team_id, total in error_tracking_api.get_issue_counts_by_team()]


def _symbol_sets_count() -> list[dict[str, int]]:
    return [
        {"team_id": team_id, "total": total} for team_id, total in error_tracking_api.get_symbol_set_counts_by_team()
    ]


def _resolved_symbol_sets_count() -> list[dict[str, int]]:
    return [
        {"team_id": team_id, "total": total}
        for team_id, total in error_tracking_api.get_symbol_set_counts_by_team(resolved_only=True)
    ]


# ---- Multi-key fan-out helpers ----------------------------------------------


def _exceptions_captured(begin: datetime, end: datetime) -> dict[str, list[list[int]]]:
    """Wrap `get_teams_with_exceptions_captured_in_period` to return a flat
    dict-of-rows keyed by source_key. The aggregator remaps these source_keys
    into the destination `all_data` keys via `multi_keys_mapping` below.
    """
    library_totals, team_totals_list = get_teams_with_exceptions_captured_in_period(begin, end)
    out: dict[str, list[list[int]]] = {"total": team_totals_list}
    for library, rows in library_totals.items():
        out[library] = rows
    return out


# ---- Registry ---------------------------------------------------------------


# Period queries filter on (begin, end) and are re-run safe.
PeriodFn = Callable[[datetime, datetime], Any]
# Snapshot queries take no args — they read current state and are *not*
# re-run safe. See the module-level disclaimer above.
SnapshotFn = Callable[[], Any]


@dataclasses.dataclass(frozen=True)
class QuerySpec:
    name: str
    fn: PeriodFn | SnapshotFn
    output: Literal["single", "multi"] = "single"
    # For output="multi" specs only: maps source-keys returned by fn to
    # destination keys in the flat `all_data` dict.
    multi_keys_mapping: dict[str, str] = dataclasses.field(default_factory=dict)
    timeout_minutes: int = 15
    kind: Literal["period", "snapshot"] = "period"


QUERIES: list[QuerySpec] = [
    # ---- ClickHouse: events --------------------------------------------------
    QuerySpec(
        name="teams_with_event_count_in_period",
        fn=lambda b, e: get_teams_with_billable_event_count_in_period(b, e, count_distinct=True),
        timeout_minutes=30,
    ),
    QuerySpec(
        name="teams_with_enhanced_persons_event_count_in_period",
        fn=lambda b, e: get_teams_with_billable_enhanced_persons_event_count_in_period(b, e, count_distinct=True),
        timeout_minutes=30,
    ),
    QuerySpec(
        name="teams_with_event_count_with_groups_in_period",
        fn=get_teams_with_event_count_with_groups_in_period,
    ),
    QuerySpec(
        name="all_event_metrics",
        fn=get_all_event_metrics_in_period,
        output="multi",
        multi_keys_mapping={
            "helicone_events": "teams_with_event_count_from_helicone_in_period",
            "langfuse_events": "teams_with_event_count_from_langfuse_in_period",
            "keywords_ai_events": "teams_with_event_count_from_keywords_ai_in_period",
            "traceloop_events": "teams_with_event_count_from_traceloop_in_period",
            "web_events": "teams_with_web_events_count_in_period",
            "web_lite_events": "teams_with_web_lite_events_count_in_period",
            "node_events": "teams_with_node_events_count_in_period",
            "android_events": "teams_with_android_events_count_in_period",
            "flutter_events": "teams_with_flutter_events_count_in_period",
            "ios_events": "teams_with_ios_events_count_in_period",
            "go_events": "teams_with_go_events_count_in_period",
            "java_events": "teams_with_java_events_count_in_period",
            "react_native_events": "teams_with_react_native_events_count_in_period",
            "ruby_events": "teams_with_ruby_events_count_in_period",
            "python_events": "teams_with_python_events_count_in_period",
            "php_events": "teams_with_php_events_count_in_period",
            "dotnet_events": "teams_with_dotnet_events_count_in_period",
            "elixir_events": "teams_with_elixir_events_count_in_period",
            "unity_events": "teams_with_unity_events_count_in_period",
            "rust_events": "teams_with_rust_events_count_in_period",
        },
        timeout_minutes=30,
    ),
    # ---- ClickHouse: recordings ----------------------------------------------
    QuerySpec(
        name="teams_with_recording_count_in_period",
        fn=lambda b, e: get_teams_with_recording_count_in_period(b, e, snapshot_source="web"),
    ),
    QuerySpec(
        name="teams_with_zero_duration_recording_count_in_period",
        fn=get_teams_with_zero_duration_recording_count_in_period,
    ),
    QuerySpec(
        name="teams_with_recording_bytes_in_period",
        fn=lambda b, e: get_teams_with_recording_bytes_in_period(b, e, snapshot_source="web"),
    ),
    QuerySpec(
        name="teams_with_mobile_recording_count_in_period",
        fn=lambda b, e: get_teams_with_recording_count_in_period(b, e, snapshot_source="mobile"),
    ),
    QuerySpec(
        name="teams_with_mobile_recording_bytes_in_period",
        fn=lambda b, e: get_teams_with_recording_bytes_in_period(b, e, snapshot_source="mobile"),
    ),
    QuerySpec(
        name="teams_with_mobile_billable_recording_count_in_period",
        fn=get_teams_with_mobile_billable_recording_count_in_period,
    ),
    # ---- ClickHouse: feature flag requests -----------------------------------
    QuerySpec(
        name="teams_with_decide_requests_count_in_period",
        fn=lambda b, e: get_teams_with_feature_flag_requests_count_in_period(b, e, FlagRequestType.DECIDE),
    ),
    QuerySpec(
        name="teams_with_local_evaluation_requests_count_in_period",
        fn=lambda b, e: get_teams_with_feature_flag_requests_count_in_period(b, e, FlagRequestType.LOCAL_EVALUATION),
    ),
    # ---- ClickHouse: query metrics -------------------------------------------
    QuerySpec(
        name="teams_with_query_app_bytes_read",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="read_bytes", access_method=""),
    ),
    QuerySpec(
        name="teams_with_query_app_rows_read",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="read_rows", access_method=""),
    ),
    QuerySpec(
        name="teams_with_query_app_duration_ms",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="query_duration_ms", access_method=""),
    ),
    QuerySpec(
        name="teams_with_query_api_bytes_read",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="read_bytes", access_method="personal_api_key"),
    ),
    QuerySpec(
        name="teams_with_query_api_rows_read",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="read_rows", access_method="personal_api_key"),
    ),
    QuerySpec(
        name="teams_with_query_api_duration_ms",
        fn=lambda b, e: get_teams_with_query_metric(b, e, metric="query_duration_ms", access_method="personal_api_key"),
    ),
    QuerySpec(
        name="api_queries_metrics",
        fn=get_teams_with_api_queries_metrics,
        output="multi",
        multi_keys_mapping={
            "count": "teams_with_api_queries_count",
            "read_bytes": "teams_with_api_queries_read_bytes",
        },
    ),
    # ---- ClickHouse: event explorer ------------------------------------------
    QuerySpec(
        name="teams_with_event_explorer_app_bytes_read",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="read_bytes", query_types=["EventsQuery"], access_method=""
        ),
    ),
    QuerySpec(
        name="teams_with_event_explorer_app_rows_read",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="read_rows", query_types=["EventsQuery"], access_method=""
        ),
    ),
    QuerySpec(
        name="teams_with_event_explorer_app_duration_ms",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="query_duration_ms", query_types=["EventsQuery"], access_method=""
        ),
    ),
    QuerySpec(
        name="teams_with_event_explorer_api_bytes_read",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="read_bytes", query_types=["EventsQuery"], access_method="personal_api_key"
        ),
    ),
    QuerySpec(
        name="teams_with_event_explorer_api_rows_read",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="read_rows", query_types=["EventsQuery"], access_method="personal_api_key"
        ),
    ),
    QuerySpec(
        name="teams_with_event_explorer_api_duration_ms",
        fn=lambda b, e: get_teams_with_query_metric(
            b, e, metric="query_duration_ms", query_types=["EventsQuery"], access_method="personal_api_key"
        ),
    ),
    # ---- ClickHouse: surveys -------------------------------------------------
    QuerySpec(
        name="teams_with_survey_responses_count_in_period",
        fn=get_teams_with_survey_responses_count_in_period,
    ),
    # ---- ClickHouse: data warehouse / batch exports usage --------------------
    QuerySpec(
        name="teams_with_rows_synced_in_period",
        fn=get_teams_with_rows_synced_in_period,
    ),
    QuerySpec(
        name="teams_with_free_historical_rows_synced_in_period",
        fn=get_teams_with_free_historical_rows_synced_in_period,
    ),
    QuerySpec(
        name="teams_with_rows_exported_in_period",
        fn=get_teams_with_rows_exported_in_period,
    ),
    # ---- ClickHouse: exceptions / error tracking events ----------------------
    QuerySpec(
        name="exceptions_captured",
        fn=_exceptions_captured,
        output="multi",
        multi_keys_mapping={
            "total": "teams_with_exceptions_captured_in_period",
            "web": "teams_with_web_exceptions_captured_in_period",
            "web_lite": "teams_with_js_lite_exceptions_captured_in_period",
            "node": "teams_with_node_exceptions_captured_in_period",
            "go": "teams_with_go_exceptions_captured_in_period",
            "java": "teams_with_java_exceptions_captured_in_period",
            "ruby": "teams_with_ruby_exceptions_captured_in_period",
            "python": "teams_with_python_exceptions_captured_in_period",
            "android": "teams_with_android_exceptions_captured_in_period",
            "react_native": "teams_with_react_native_exceptions_captured_in_period",
            "ios": "teams_with_ios_exceptions_captured_in_period",
            "flutter": "teams_with_flutter_exceptions_captured_in_period",
            "unknown": "teams_with_unknown_exceptions_captured_in_period",
        },
    ),
    # ---- ClickHouse: hog functions / CDP ------------------------------------
    QuerySpec(
        name="teams_with_hog_function_calls_in_period",
        fn=get_teams_with_hog_function_calls_in_period,
    ),
    QuerySpec(
        name="teams_with_hog_function_fetch_calls_in_period",
        fn=get_teams_with_hog_function_fetch_calls_in_period,
    ),
    QuerySpec(
        name="teams_with_cdp_billable_invocations_in_period",
        fn=get_teams_with_cdp_billable_invocations_in_period,
    ),
    # ---- ClickHouse: AI ------------------------------------------------------
    QuerySpec(
        name="teams_with_ai_event_count_in_period",
        fn=get_teams_with_ai_event_count_in_period,
    ),
    QuerySpec(
        name="teams_with_ai_credits_used_in_period",
        fn=get_teams_with_ai_credits_used_in_period,
    ),
    # ---- ClickHouse: workflows / messaging ----------------------------------
    QuerySpec(
        name="teams_with_workflow_emails_sent_in_period",
        fn=get_teams_with_workflow_emails_sent_in_period,
    ),
    QuerySpec(
        name="teams_with_workflow_push_sent_in_period",
        fn=get_teams_with_workflow_push_sent_in_period,
    ),
    QuerySpec(
        name="teams_with_workflow_sms_sent_in_period",
        fn=get_teams_with_workflow_sms_sent_in_period,
    ),
    QuerySpec(
        name="teams_with_workflow_billable_invocations_in_period",
        fn=get_teams_with_workflow_billable_invocations_in_period,
    ),
    # ---- ClickHouse: logs ---------------------------------------------------
    QuerySpec(
        name="teams_with_logs_bytes_in_period",
        fn=get_teams_with_logs_bytes_in_period,
    ),
    QuerySpec(
        name="teams_with_logs_records_in_period",
        fn=get_teams_with_logs_records_in_period,
    ),
    # ---- Snapshot queries (kind="snapshot") ---------------------------------
    # ⚠️  Read the disclaimer at the top of this module. These ignore the
    # period and reflect *current* state at run time. Re-running for the same
    # date can return different numbers if state has changed since.
    QuerySpec(
        name="teams_with_active_external_data_schemas_in_period",
        fn=get_teams_with_active_external_data_schemas_in_period,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_active_batch_exports_in_period",
        fn=get_teams_with_active_batch_exports_in_period,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dwh_tables_storage_in_s3_in_mib",
        fn=get_teams_with_dwh_tables_storage_in_s3,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dwh_mat_views_storage_in_s3_in_mib",
        fn=get_teams_with_dwh_mat_views_storage_in_s3,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dwh_total_storage_in_s3_in_mib",
        fn=get_teams_with_dwh_total_storage_in_s3,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_active_hog_destinations_in_period",
        fn=get_teams_with_active_hog_destinations_in_period,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_active_hog_transformations_in_period",
        fn=get_teams_with_active_hog_transformations_in_period,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_group_types_total",
        fn=_group_types_total,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dashboard_count",
        fn=_dashboard_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dashboard_template_count",
        fn=_dashboard_template_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dashboard_shared_count",
        fn=_dashboard_shared_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_dashboard_tagged_count",
        fn=_dashboard_tagged_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_ff_count",
        fn=_ff_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_ff_active_count",
        fn=_ff_active_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_survey_count",
        fn=_survey_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_issues_created_total",
        fn=_issues_created_total,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_symbol_sets_count",
        fn=_symbol_sets_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
    QuerySpec(
        name="teams_with_resolved_symbol_sets_count",
        fn=_resolved_symbol_sets_count,
        timeout_minutes=5,
        kind="snapshot",
    ),
]


QUERY_INDEX: dict[str, QuerySpec] = {spec.name: spec for spec in QUERIES}
