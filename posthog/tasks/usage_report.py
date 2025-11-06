import os
import gzip
import json
import base64
import logging
import dataclasses
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional, TypedDict, Union

from django.conf import settings
from django.db import connection
from django.db.models import Count, F, Q, Sum

import requests
import structlog
from cachetools import cached
from celery import shared_task
from dateutil import parser
from posthoganalytics.client import Client as PostHogClient
from psycopg import sql
from retry import retry

from posthog.schema import AIEventType

from posthog import version_requirement
from posthog.batch_exports.models import BatchExportDestination, BatchExportRun
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import get_cached_instance_license
from posthog.constants import FlagRequestType
from posthog.exceptions_capture import capture_exception
from posthog.logging.timing import timed_log
from posthog.models import BatchExport, GroupTypeMapping, OrganizationMembership, User
from posthog.models.dashboard import Dashboard
from posthog.models.feature_flag import FeatureFlag
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.organization import Organization
from posthog.models.plugin import PluginConfig
from posthog.models.property.util import get_property_string_expr
from posthog.models.surveys.util import get_unique_survey_event_uuids_sql_subquery
from posthog.models.team.team import Team
from posthog.models.utils import namedtuplefetchall
from posthog.settings import CLICKHOUSE_CLUSTER, INSTANCE_TAG
from posthog.tasks.report_utils import capture_event
from posthog.tasks.utils import CeleryQueue
from posthog.utils import get_helm_info_env, get_instance_realm, get_instance_region, get_previous_day

from products.data_warehouse.backend.models import (
    DataWarehouseSavedQuery,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSymbolSet

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)

# AI events dynamically generated from AIEventType TS enum
# Changes to the AIEventType enum will impact usage reporting
AI_EVENTS = [event.value for event in AIEventType]


class Period(TypedDict):
    start_inclusive: str
    end_inclusive: str


class TableSizes(TypedDict):
    posthog_event: int
    posthog_sessionrecordingevent: int


CH_BILLING_SETTINGS = {
    "max_execution_time": 5 * 60,  # 5 minutes
}

QUERY_RETRIES = 3
QUERY_RETRY_DELAY = 1
QUERY_RETRY_BACKOFF = 2

USAGE_REPORT_TASK_KWARGS = {
    "queue": CeleryQueue.USAGE_REPORTS.value,
    "ignore_result": True,
    "acks_late": True,
    "reject_on_worker_lost": True,
    "autoretry_for": (Exception,),
    "retry_backoff": 300,  # 5min
    "retry_backoff_max": 1800,  # 30min
    "expires": 14400,  # 4h
}


@dataclasses.dataclass
class UsageReportCounters:
    event_count_in_period: int
    enhanced_persons_event_count_in_period: int
    event_count_with_groups_in_period: int
    event_count_from_langfuse_in_period: int
    event_count_from_helicone_in_period: int
    event_count_from_keywords_ai_in_period: int
    event_count_from_traceloop_in_period: int

    # Recordings
    recording_count_in_period: int
    recording_bytes_in_period: int
    zero_duration_recording_count_in_period: int
    mobile_recording_count_in_period: int
    mobile_recording_bytes_in_period: int
    mobile_billable_recording_count_in_period: int
    # Persons and Groups
    group_types_total: int
    # Dashboards
    dashboard_count: int
    dashboard_template_count: int
    dashboard_shared_count: int
    dashboard_tagged_count: int
    # Feature flags
    ff_count: int
    ff_active_count: int
    decide_requests_count_in_period: int
    local_evaluation_requests_count_in_period: int
    billable_feature_flag_requests_count_in_period: int
    # Queries
    query_app_bytes_read: int
    query_app_rows_read: int
    query_app_duration_ms: int
    query_api_bytes_read: int
    query_api_rows_read: int
    query_api_duration_ms: int

    # API Queries usage
    api_queries_query_count: int
    api_queries_bytes_read: int

    # Event Explorer
    event_explorer_app_bytes_read: int
    event_explorer_app_rows_read: int
    event_explorer_app_duration_ms: int
    event_explorer_api_bytes_read: int
    event_explorer_api_rows_read: int
    event_explorer_api_duration_ms: int
    # Surveys
    survey_responses_count_in_period: int
    # Data Warehouse
    rows_synced_in_period: int
    free_historical_rows_synced_in_period: int

    # Data Warehouse metadata
    active_external_data_schemas_in_period: int

    # Batch Exports metadata
    rows_exported_in_period: int
    active_batch_exports_in_period: int

    dwh_total_storage_in_s3_in_mib: float
    dwh_tables_storage_in_s3_in_mib: float
    dwh_mat_views_storage_in_s3_in_mib: float
    # Error Tracking
    issues_created_total: int
    symbol_sets_count: int
    resolved_symbol_sets_count: int
    exceptions_captured_in_period: int
    # LLM Analytics
    ai_event_count_in_period: int
    # CDP Delivery
    hog_function_calls_in_period: int
    hog_function_fetch_calls_in_period: int
    cdp_billable_invocations_in_period: int
    # SDK usage
    web_events_count_in_period: int
    web_lite_events_count_in_period: int
    node_events_count_in_period: int
    android_events_count_in_period: int
    flutter_events_count_in_period: int
    ios_events_count_in_period: int
    go_events_count_in_period: int
    java_events_count_in_period: int
    react_native_events_count_in_period: int
    ruby_events_count_in_period: int
    python_events_count_in_period: int
    php_events_count_in_period: int
    dotnet_events_count_in_period: int
    elixir_events_count_in_period: int
    active_hog_destinations_in_period: int
    active_hog_transformations_in_period: int


# Instance metadata to be included in overall report
@dataclasses.dataclass
class InstanceMetadata:
    deployment_infrastructure: str
    realm: str
    period: Period
    site_url: str
    product: str
    helm: Optional[dict]
    clickhouse_version: Optional[str]
    users_who_logged_in: Optional[list[dict[str, Union[str, int]]]]
    users_who_logged_in_count: Optional[int]
    users_who_signed_up: Optional[list[dict[str, Union[str, int]]]]
    users_who_signed_up_count: Optional[int]
    table_sizes: Optional[TableSizes]
    plugins_installed: Optional[dict]
    plugins_enabled: Optional[dict]
    instance_tag: str


@dataclasses.dataclass
class OrgReport(UsageReportCounters):
    date: str
    organization_id: str
    organization_name: str
    organization_created_at: str
    organization_user_count: int
    team_count: int
    teams: dict[str, UsageReportCounters]


@dataclasses.dataclass
class FullUsageReport(OrgReport, InstanceMetadata):
    pass


def fetch_table_size(table_name: str) -> int:
    return fetch_sql("SELECT pg_total_relation_size(%s) as size", (table_name,))[0].size


def fetch_sql(sql_: str, params: tuple[Any, ...]) -> list[Any]:
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL(sql_), params)
        return namedtuplefetchall(cursor)


def get_product_name(realm: str, has_license: bool) -> str:
    if realm == "cloud":
        return "cloud"
    elif realm in {"hosted", "hosted-clickhouse"}:
        return "scale" if has_license else "open source"
    else:
        return "unknown"


def get_instance_metadata(period: tuple[datetime, datetime]) -> InstanceMetadata:
    has_license = False

    if settings.EE_AVAILABLE:
        license = get_cached_instance_license()
        has_license = license is not None

    period_start, period_end = period

    realm = get_instance_realm()
    metadata = InstanceMetadata(
        deployment_infrastructure=os.getenv("DEPLOYMENT", "unknown"),
        realm=realm,
        period={
            "start_inclusive": period_start.isoformat(),
            "end_inclusive": period_end.isoformat(),
        },
        site_url=settings.SITE_URL,
        product=get_product_name(realm, has_license),
        # Non-cloud vars
        helm=None,
        clickhouse_version=None,
        users_who_logged_in=None,
        users_who_logged_in_count=None,
        users_who_signed_up=None,
        users_who_signed_up_count=None,
        table_sizes=None,
        plugins_installed=None,
        plugins_enabled=None,
        instance_tag=INSTANCE_TAG,
    )

    if realm != "cloud":
        metadata.helm = get_helm_info_env()
        metadata.clickhouse_version = str(version_requirement.get_clickhouse_version())

        metadata.users_who_logged_in = [
            (
                {"id": user.id, "distinct_id": user.distinct_id}
                if user.anonymize_data
                else {
                    "id": user.id,
                    "distinct_id": user.distinct_id,
                    "first_name": user.first_name,
                    "email": user.email,
                }
            )
            for user in User.objects.filter(is_active=True, last_login__gte=period_start, last_login__lte=period_end)
        ]
        metadata.users_who_logged_in_count = len(metadata.users_who_logged_in)

        metadata.users_who_signed_up = [
            (
                {"id": user.id, "distinct_id": user.distinct_id}
                if user.anonymize_data
                else {
                    "id": user.id,
                    "distinct_id": user.distinct_id,
                    "first_name": user.first_name,
                    "email": user.email,
                }
            )
            for user in User.objects.filter(
                is_active=True,
                date_joined__gte=period_start,
                date_joined__lte=period_end,
            )
        ]
        metadata.users_who_signed_up_count = len(metadata.users_who_signed_up)

        metadata.table_sizes = {
            "posthog_event": fetch_table_size("posthog_event"),
            "posthog_sessionrecordingevent": fetch_table_size("posthog_sessionrecordingevent"),
        }

        plugin_configs = PluginConfig.objects.select_related("plugin").all()

        metadata.plugins_installed = dict(Counter(plugin_config.plugin.name for plugin_config in plugin_configs))
        metadata.plugins_enabled = dict(
            Counter(plugin_config.plugin.name for plugin_config in plugin_configs if plugin_config.enabled)
        )

    return metadata


def get_org_user_count(organization_id: str) -> int:
    return OrganizationMembership.objects.filter(organization_id=organization_id).count()


@cached(cache={})
def get_ph_client(*args: Any, **kwargs: Any) -> PostHogClient:
    return PostHogClient("sTMFPsFhdP1Ssg", *args, **kwargs)


@shared_task(**USAGE_REPORT_TASK_KWARGS, max_retries=3, rate_limit="5/s")
def send_report_to_billing_service(org_id: str, report: dict[str, Any]) -> None:
    if not settings.EE_AVAILABLE:
        return

    from products.enterprise.backend.billing.billing_manager import BillingManager, build_billing_token
    from products.enterprise.backend.billing.billing_types import BillingStatus
    from products.enterprise.backend.settings import BILLING_SERVICE_URL

    try:
        license = get_cached_instance_license()
        if not license or not license.is_v2_license:
            return

        organization = Organization.objects.get(id=org_id)
        if not organization:
            return

        token = build_billing_token(license, organization)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.post(f"{BILLING_SERVICE_URL}/api/usage", json=report, headers=headers, timeout=30)
        if response.status_code != 200:
            raise Exception(
                f"Failed to send usage report to billing service code:{response.status_code} response:{response.text}"
            )

        response_data: BillingStatus = response.json()
        BillingManager(license).update_org_details(organization, response_data)

    except Exception as err:
        logger.exception(
            f"[Send Usage Report To Billing] Usage Report failed sending to Billing for organization: {org_id}: {err}"
        )
        capture_exception(err)
        capture_event(
            pha_client=get_ph_client(sync_mode=True),
            name=f"organization usage report to billing service failure",
            organization_id=org_id,
            properties={"err": str(err)},
        )
        raise


def _execute_split_query(
    begin: datetime,
    end: datetime,
    query_template: str,
    params: dict,
    num_splits: int = 2,
    combine_results_func: Optional[Callable[[list], Any]] = None,
) -> Any:
    """
    Helper function to execute a query split into multiple parts to reduce load.
    Splits the time period into num_splits parts and runs separate queries, then combines the results.

    Args:
        begin: Start of the time period
        end: End of the time period
        query_template: SQL query template with %(begin)s and %(end)s placeholders
        params: Additional parameters for the query
        num_splits: Number of time splits to make (default: 2)
        combine_results_func: Optional function to combine results from multiple queries
                             If None, uses the default team_id count combiner

    Returns:
        Combined query results
    """
    # Calculate the time interval for each split
    time_delta = (end - begin) / num_splits

    all_results = []

    # Execute query for each time split
    for i in range(num_splits):
        split_begin = begin + (time_delta * i)
        split_end = begin + (time_delta * (i + 1))

        # For the last split, use the exact end time to avoid rounding issues
        if i == num_splits - 1:
            split_end = end

        # Create a copy of params and update with the split time range
        split_params = params.copy()
        split_params["begin"] = split_begin
        split_params["end"] = split_end

        # Execute the query for this time split
        split_result = sync_execute(
            query_template,
            split_params,
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )

        all_results.append(split_result)

    # If no custom combine function is provided, use the default team_id count combiner
    if combine_results_func is None:
        return _combine_team_count_results(all_results)
    else:
        return combine_results_func(all_results)


def _combine_team_count_results(results_list: list) -> list[tuple[int, int]]:
    """
    Default function to combine results from multiple queries that return (team_id, count) tuples.

    Args:
        results_list: List of query results, each containing (team_id, count) tuples

    Returns:
        Combined list of (team_id, count) tuples
    """
    team_counts: dict[int, int] = {}

    # Combine all results
    for results in results_list:
        for team_id, count in results:
            if team_id in team_counts:
                team_counts[team_id] += count
            else:
                team_counts[team_id] = count

    # Convert back to the expected format
    return list(team_counts.items())


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_billable_event_count_in_period(
    begin: datetime, end: datetime, count_distinct: bool = False
) -> list[tuple[int, int]]:
    # count only unique events
    # Duplicate events will be eventually removed by ClickHouse and likely came from our library or pipeline.
    # We shouldn't bill for these. However counting unique events is more expensive, and likely to fail on longer time ranges.
    # So, we count uniques in small time periods only, controlled by the count_distinct parameter.
    if count_distinct:
        # Uses the same expression as the one used to de-duplicate events on the merge tree:
        # https://github.com/PostHog/posthog/blob/master/posthog/models/event/sql.py#L92
        distinct_expression = "distinct toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid)"
    else:
        distinct_expression = "1"

    # We are excluding $exception events during the beta
    # We also exclude AI events as they are billed separately through ai_event_count_in_period
    excluded_events = [
        "$feature_flag_called",
        "survey sent",
        "survey shown",
        "survey dismissed",
        "$exception",
        *AI_EVENTS,
    ]

    query_template = f"""
        SELECT team_id, count({distinct_expression}) as count
        FROM events
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
            AND event NOT IN %(excluded_events)s
        GROUP BY team_id
    """

    return _execute_split_query(begin, end, query_template, {"excluded_events": excluded_events}, num_splits=3)


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_billable_enhanced_persons_event_count_in_period(
    begin: datetime, end: datetime, count_distinct: bool = False
) -> list[tuple[int, int]]:
    # count only unique events
    # Duplicate events will be eventually removed by ClickHouse and likely came from our library or pipeline.
    # We shouldn't bill for these. However counting unique events is more expensive, and likely to fail on longer time ranges.
    # So, we count uniques in small time periods only, controlled by the count_distinct parameter.
    if count_distinct:
        # Uses the same expression as the one used to de-duplicate events on the merge tree:
        # https://github.com/PostHog/posthog/blob/master/posthog/models/event/sql.py#L92
        distinct_expression = "distinct toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid)"
    else:
        distinct_expression = "1"

    # We exclude AI events as they are billed separately through ai_event_count_in_period
    excluded_events = [
        "$feature_flag_called",
        "survey sent",
        "survey shown",
        "survey dismissed",
        "$exception",
        *AI_EVENTS,
    ]

    query_template = f"""
        SELECT team_id, count({distinct_expression}) as count
        FROM events
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
            AND event NOT IN %(excluded_events)s
            AND person_mode IN ('full', 'force_upgrade')
        GROUP BY team_id
    """

    return _execute_split_query(begin, end, query_template, {"excluded_events": excluded_events}, num_splits=3)


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_event_count_with_groups_in_period(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    result = sync_execute(
        """
        SELECT team_id, count(1) as count
        FROM events
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
        AND ($group_0 != '' OR $group_1 != '' OR $group_2 != '' OR $group_3 != '' OR $group_4 != '')
        GROUP BY team_id
        """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )
    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_all_event_metrics_in_period(begin: datetime, end: datetime) -> dict[str, list[tuple[int, int]]]:
    # Check if $lib is materialized
    lib_expression, _ = get_property_string_expr("events", "$lib", "'$lib'", "properties")

    query_template = f"""
        SELECT
            team_id,
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
                'other'
            ) AS metric,
            count(1) as count
        FROM events
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id, metric
        HAVING metric != 'other'
    """

    # Define a custom function to combine results from multiple queries
    def combine_event_metrics_results(results_list: list) -> dict[str, list[tuple[int, int]]]:
        metrics: dict[str, dict[int, int]] = {
            "helicone_events": {},
            "langfuse_events": {},
            "keywords_ai_events": {},
            "traceloop_events": {},
            "web_events": {},
            "web_lite_events": {},
            "node_events": {},
            "android_events": {},
            "flutter_events": {},
            "ios_events": {},
            "go_events": {},
            "java_events": {},
            "react_native_events": {},
            "ruby_events": {},
            "python_events": {},
            "php_events": {},
            "dotnet_events": {},
            "elixir_events": {},
        }

        # Process each result set
        for results in results_list:
            for team_id, metric, count in results:
                if metric in metrics:  # Make sure the metric exists in our dictionary
                    if team_id in metrics[metric]:
                        metrics[metric][team_id] += count
                    else:
                        metrics[metric][team_id] = count

        # Convert to the expected format
        result = {}
        for metric, team_counts in metrics.items():
            result[metric] = list(team_counts.items())

        return result

    # Execute the split query with 3 splits
    return _execute_split_query(
        begin=begin,
        end=end,
        query_template=query_template,
        params={},
        num_splits=3,
        combine_results_func=combine_event_metrics_results,
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_recording_count_in_period(
    begin: datetime, end: datetime, snapshot_source: Literal["mobile", "web"] = "web"
) -> list[tuple[int, int]]:
    previous_begin = begin - (end - begin)

    result = sync_execute(
        """
        SELECT team_id, count(distinct session_id) as count
        FROM (
            SELECT any(team_id) as team_id, session_id
            FROM session_replay_events
            WHERE min_first_timestamp >= %(begin)s AND min_first_timestamp < %(end)s
            GROUP BY session_id
            HAVING ifNull(argMinMerge(snapshot_source), 'web') == %(snapshot_source)s
        )
        WHERE session_id NOT IN (
            -- we want to exclude sessions that might have events with timestamps
            -- before the period we are interested in
            SELECT DISTINCT session_id
            FROM session_replay_events
            -- begin is the very first instant of the period we are interested in
            -- we assume it is also the very first instant of a day
            -- so we can to subtract 1 second to get the day before
            WHERE min_first_timestamp >= %(previous_begin)s AND min_first_timestamp < %(begin)s
            GROUP BY session_id
        )
        GROUP BY team_id
    """,
        {"previous_begin": previous_begin, "begin": begin, "end": end, "snapshot_source": snapshot_source},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_zero_duration_recording_count_in_period(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    previous_begin = begin - (end - begin)

    result = sync_execute(
        """
        SELECT team_id, count(distinct session_id) as count
        FROM (
            SELECT any(team_id) as team_id, session_id
            FROM session_replay_events
            WHERE min_first_timestamp >= %(begin)s AND min_first_timestamp < %(end)s
            GROUP BY session_id
            HAVING dateDiff('milliseconds', min(min_first_timestamp), max(max_last_timestamp)) = 0
        )
        WHERE session_id NOT IN (
            -- we want to exclude sessions that might have events with timestamps
            -- before the period we are interested in
            SELECT DISTINCT session_id
            FROM session_replay_events
            -- begin is the very first instant of the period we are interested in
            -- we assume it is also the very first instant of a day
            -- so we can to subtract 1 second to get the day before
            WHERE min_first_timestamp >= %(previous_begin)s AND min_first_timestamp < %(begin)s
            GROUP BY session_id
        )
        GROUP BY team_id
    """,
        {"previous_begin": previous_begin, "begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_mobile_billable_recording_count_in_period(begin: datetime, end: datetime) -> list[tuple[int, int]]:
    previous_begin = begin - (end - begin)

    result = sync_execute(
        """
        SELECT team_id, count(distinct session_id) as count
        FROM (
            SELECT any(team_id) as team_id, session_id
            FROM session_replay_events
            WHERE min_first_timestamp >= %(begin)s AND min_first_timestamp < %(end)s
            GROUP BY session_id
            HAVING (ifNull(argMinMerge(snapshot_source), '') == 'mobile'
            AND ifNull(argMinMerge(snapshot_library), '') IN ('posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'))
        )
        WHERE session_id NOT IN (
            -- we want to exclude sessions that might have events with timestamps
            -- before the period we are interested in
            SELECT DISTINCT session_id
            FROM session_replay_events
            -- begin is the very first instant of the period we are interested in
            -- we assume it is also the very first instant of a day
            -- so we can to subtract 1 second to get the day before
            WHERE min_first_timestamp >= %(previous_begin)s AND min_first_timestamp < %(begin)s
            GROUP BY session_id
        )
        GROUP BY team_id
    """,
        {"previous_begin": previous_begin, "begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_api_queries_metrics(
    begin: datetime,
    end: datetime,
) -> dict[str, list[tuple[int, int]]]:
    # Intentionally uses event_time not query_start_time, the difference between values is on avg 1.5s,
    # the former is part of primary key, the latter not.
    query = f"""
        SELECT JSONExtractInt(log_comment, 'team_id') team_id, count(1) cnt, sum(read_bytes) read_bytes
        FROM clusterAllReplicas({CLICKHOUSE_CLUSTER}, system.query_log)
        WHERE type = 'QueryFinish'
        AND is_initial_query
        AND event_time >= %(begin)s AND event_time < %(end)s
        AND team_id > 0
        AND JSONExtractBool(log_comment, 'chargeable')
        GROUP BY team_id
    """
    with tags_context(usage_report="get_teams_with_api_queries_metrics"):
        results = sync_execute(
            query,
            {
                "begin": begin,
                "end": end,
            },
            workload=Workload.OFFLINE,
            settings=CH_BILLING_SETTINGS,
        )
    result_count: list[tuple[int, int]] = []
    result_read_bytes: list[tuple[int, int]] = []
    for team_id, count, read_bytes in results:
        result_count.append((team_id, count))
        result_read_bytes.append((team_id, read_bytes))
    return {"count": result_count, "read_bytes": result_read_bytes}


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_query_metric(
    begin: datetime,
    end: datetime,
    query_types: Optional[list[str]] = None,
    access_method: str = "",
    metric: Literal["read_bytes", "read_rows", "query_duration_ms"] = "read_bytes",
) -> list[tuple[int, int]]:
    if metric not in ["read_bytes", "read_rows", "query_duration_ms"]:
        # :TRICKY: Inlined into the query below.
        raise ValueError(f"Invalid metric {metric}")

    query_types_clause = "AND query_type IN (%(query_types)s)" if query_types and len(query_types) > 0 else ""

    query = f"""
        WITH JSONExtractInt(log_comment, 'team_id') as team_id,
            JSONExtractString(log_comment, 'query_type') as query_type,
            JSONExtractString(log_comment, 'access_method') as access_method
        SELECT team_id, sum({metric}) as count
        FROM clusterAllReplicas({CLICKHOUSE_CLUSTER}, system.query_log)
        WHERE (type = 'QueryFinish' OR type = 'ExceptionWhileProcessing')
        AND is_initial_query = 1
        {query_types_clause}
        AND query_start_time >= %(begin)s AND query_start_time < %(end)s
        AND access_method = %(access_method)s
        GROUP BY team_id
    """
    result = sync_execute(
        query,
        {
            "begin": begin,
            "end": end,
            "query_types": query_types,
            "access_method": access_method,
        },
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )
    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_feature_flag_requests_count_in_period(
    begin: datetime, end: datetime, request_type: FlagRequestType
) -> list[tuple[int, int]]:
    # depending on the region, events are stored in different teams
    team_to_query = 1 if get_instance_region() == "EU" else 2
    validity_token = settings.DECIDE_BILLING_ANALYTICS_TOKEN

    target_event = "decide usage" if request_type == FlagRequestType.DECIDE else "local evaluation usage"

    result = sync_execute(
        """
        SELECT distinct_id as team, sum(JSONExtractInt(properties, 'count')) as sum
        FROM events
        WHERE team_id = %(team_to_query)s AND event=%(target_event)s AND timestamp >= %(begin)s AND timestamp < %(end)s
        AND has([%(validity_token)s], replaceRegexpAll(JSONExtractRaw(properties, 'token'), '^"|"$', ''))
        GROUP BY team
    """,
        {
            "begin": begin,
            "end": end,
            "team_to_query": team_to_query,
            "validity_token": validity_token,
            "target_event": target_event,
        },
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_survey_responses_count_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    # Construct the subquery for unique event UUIDs
    unique_uuids_subquery = get_unique_survey_event_uuids_sql_subquery(
        base_conditions_sql=[
            "timestamp >= %(begin)s AND timestamp < %(end)s",
        ],
        group_by_prefix_expressions=[
            "team_id",
            "JSONExtractString(properties, '$survey_id')",  # Deduplicate per team_id, per survey_id
        ],
    )

    query = f"""
        SELECT
            team_id,
            COUNT() as count
        FROM events
        WHERE
            event = 'survey sent'
            AND timestamp >= %(begin)s AND timestamp < %(end)s
            AND uuid IN {unique_uuids_subquery}
        GROUP BY team_id
    """

    results = sync_execute(
        query,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_ai_event_count_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    results = sync_execute(
        """
        SELECT team_id, COUNT() as count
        FROM events
        WHERE event IN %(ai_events)s AND timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
    """,
        {"begin": begin, "end": end, "ai_events": AI_EVENTS},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


dwh_pricing_free_period_start = datetime(2025, 10, 29, 0, 0, 0, tzinfo=UTC)
dwh_pricing_free_period_end = datetime(2025, 11, 6, 0, 0, 0, tzinfo=UTC)


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_rows_synced_in_period(begin: datetime, end: datetime) -> list:
    if begin >= dwh_pricing_free_period_start and begin < dwh_pricing_free_period_end:
        # during the free period, everyone gets free rows synced
        return []

    if begin >= dwh_pricing_free_period_end:
        # after the free period, don't include rows reported in the free historical period
        return list(
            ExternalDataJob.objects.filter(
                ~Q(pipeline__created_at__gte=end - timedelta(days=7)),
                finished_at__gte=begin,
                finished_at__lte=end,
                billable=True,
                status=ExternalDataJob.Status.COMPLETED,
            )
            .values("team_id")
            .annotate(total=Sum("rows_synced"))
        )

    return list(
        ExternalDataJob.objects.filter(
            finished_at__gte=begin, finished_at__lte=end, billable=True, status=ExternalDataJob.Status.COMPLETED
        )
        .values("team_id")
        .annotate(total=Sum("rows_synced"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_free_historical_rows_synced_in_period(begin: datetime, end: datetime) -> list:
    if begin >= dwh_pricing_free_period_start and begin < dwh_pricing_free_period_end:
        # during the free period, all rows get reported as free historical rows synced
        return list(
            ExternalDataJob.objects.filter(
                finished_at__gte=begin, finished_at__lte=end, billable=True, status=ExternalDataJob.Status.COMPLETED
            )
            .values("team_id")
            .annotate(total=Sum("rows_synced"))
        )

    return list(
        ExternalDataJob.objects.filter(
            finished_at__gte=begin,
            finished_at__lte=end,
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
            pipeline__created_at__gte=end - timedelta(days=7),
        )
        .values("team_id")
        .annotate(total=Sum("rows_synced"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_rows_exported_in_period(begin: datetime, end: datetime) -> list:
    return list(
        BatchExportRun.objects.filter(
            finished_at__gte=begin,
            finished_at__lte=end,
            status=BatchExportRun.Status.COMPLETED,
            batch_export__deleted=False,
        )
        .exclude(batch_export__destination__type=BatchExportDestination.Destination.HTTP)
        .values(team_id=F("batch_export__team_id"))
        .annotate(total=Sum("records_completed"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_active_external_data_schemas_in_period() -> list:
    # get all external data schemas that are running or completed at run time
    return list(
        ExternalDataSchema.objects.filter(
            status__in=[ExternalDataSchema.Status.RUNNING, ExternalDataSchema.Status.COMPLETED]
        )
        .values("team_id")
        .annotate(total=Count("id"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_active_batch_exports_in_period() -> list:
    # get all batch exports that are active or completed at run time
    return list(BatchExport.objects.filter(paused=False).values("team_id").annotate(total=Count("id")))


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_dwh_tables_storage_in_s3() -> list:
    return list(
        DataWarehouseTable.objects.filter(
            ~Q(deleted=True), size_in_s3_mib__isnull=False, external_data_source_id__isnull=False
        )
        .values("team_id")
        .annotate(total=Sum("size_in_s3_mib"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_dwh_mat_views_storage_in_s3() -> list:
    return list(
        DataWarehouseSavedQuery.objects.filter(
            ~Q(table__deleted=True),
            Q(status=DataWarehouseSavedQuery.Status.COMPLETED) | Q(last_run_at__isnull=False),
            table__isnull=False,
            table__size_in_s3_mib__isnull=False,
        )
        .values("team_id")
        .annotate(total=Sum("table__size_in_s3_mib"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_dwh_total_storage_in_s3() -> list:
    return list(
        DataWarehouseTable.objects.filter(~Q(deleted=True), size_in_s3_mib__isnull=False)
        .values("team_id")
        .annotate(total=Sum("size_in_s3_mib"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_exceptions_captured_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    # We are excluding "persistence.isDisabled is not a function" errors because of a bug in our own SDK
    # Can be eventually removed once we're happy that the usage report for 3rd October 2025 does not need to be rerun
    results = sync_execute(
        """
        SELECT team_id, COUNT() as count
        FROM events
        WHERE
            event = '$exception' AND
            not arrayExists(x -> x != '' AND position(x, 'persistence.isDisabled is not a function') > 0, JSONExtract(coalesce(mat_$exception_values, '[]'), 'Array(String)')) AND
            timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
    """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_hog_function_calls_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    results = sync_execute(
        """
        SELECT team_id, SUM(count) as count
        FROM app_metrics2
        WHERE app_source='hog_function' AND metric_name IN ('succeeded','failed') AND timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id, metric_name
    """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_hog_function_fetch_calls_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    results = sync_execute(
        """
        SELECT team_id, SUM(count) as count
        FROM app_metrics2
        WHERE app_source='hog_function' AND metric_name IN ('fetch') AND timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id, metric_name
    """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_cdp_billable_invocations_in_period(
    begin: datetime,
    end: datetime,
) -> list[tuple[int, int]]:
    results = sync_execute(
        """
        SELECT team_id, SUM(count) as count
        FROM app_metrics2
        WHERE app_source='hog_function' AND metric_name IN ('billable_invocation') AND timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
    """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return results


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_recording_bytes_in_period(
    begin: datetime, end: datetime, snapshot_source: Literal["mobile", "web"] = "web"
) -> list[tuple[int, int]]:
    previous_begin = begin - (end - begin)

    result = sync_execute(
        """
        SELECT team_id, sum(total_size) as bytes
        FROM (
            SELECT any(team_id) as team_id, session_id, sum(size) as total_size
            FROM session_replay_events
            WHERE min_first_timestamp >= %(begin)s AND min_first_timestamp < %(end)s
            GROUP BY session_id
            HAVING ifNull(argMinMerge(snapshot_source), 'web') == %(snapshot_source)s
        )
        WHERE session_id NOT IN (
            -- we want to exclude sessions that might have events with timestamps
            -- before the period we are interested in
            SELECT DISTINCT session_id
            FROM session_replay_events
            -- begin is the very first instant of the period we are interested in
            -- we assume it is also the very first instant of a day
            -- so we can to subtract 1 second to get the day before
            WHERE min_first_timestamp >= %(previous_begin)s AND min_first_timestamp < %(begin)s
            GROUP BY session_id
        )
        GROUP BY team_id
    """,
        {"previous_begin": previous_begin, "begin": begin, "end": end, "snapshot_source": snapshot_source},
        workload=Workload.OFFLINE,
        settings=CH_BILLING_SETTINGS,
    )

    return result


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_active_hog_destinations_in_period() -> list:
    return list(
        HogFunction.objects.filter(
            type=HogFunctionType.DESTINATION,
            enabled=True,
            deleted=False,
        )
        .values("team_id")
        .annotate(total=Count("id"))
    )


@timed_log()
@retry(tries=QUERY_RETRIES, delay=QUERY_RETRY_DELAY, backoff=QUERY_RETRY_BACKOFF)
def get_teams_with_active_hog_transformations_in_period() -> list:
    return list(
        HogFunction.objects.filter(
            type=HogFunctionType.TRANSFORMATION,
            enabled=True,
            deleted=False,
        )
        .values("team_id")
        .annotate(total=Count("id"))
    )


@shared_task(**USAGE_REPORT_TASK_KWARGS, max_retries=3)
def capture_report(
    *,
    organization_id: Optional[str] = None,
    full_report_dict: dict[str, Any],
    at_date: Optional[str] = None,
) -> None:
    if not organization_id:
        raise ValueError("Organization_id must be provided")
    try:
        pha_client = get_ph_client(sync_mode=True)
        capture_event(
            pha_client=pha_client,
            name="organization usage report",
            organization_id=organization_id,
            properties=full_report_dict,
            timestamp=at_date,
        )
    except Exception as err:
        logger.exception(
            f"UsageReport sent to PostHog for organization {organization_id} failed: {str(err)}",
        )
        capture_event(
            pha_client=pha_client,
            name="organization usage report failure",
            organization_id=organization_id,
            properties={"error": str(err)},
        )


# extend this with future usage based products
def has_non_zero_usage(report: FullUsageReport) -> bool:
    return (
        report.event_count_in_period > 0
        or report.enhanced_persons_event_count_in_period > 0
        or report.recording_count_in_period > 0
        or report.mobile_recording_count_in_period > 0
        or report.decide_requests_count_in_period > 0
        or report.local_evaluation_requests_count_in_period > 0
        or report.survey_responses_count_in_period > 0
        or report.rows_synced_in_period > 0
        or report.free_historical_rows_synced_in_period > 0
        or report.cdp_billable_invocations_in_period > 0
        or report.rows_exported_in_period > 0
        or report.exceptions_captured_in_period > 0
        or report.ai_event_count_in_period > 0
    )


def convert_team_usage_rows_to_dict(rows: list[Union[dict, tuple[int, int]]]) -> dict[int, int]:
    team_id_map = {}
    for row in rows:
        if isinstance(row, dict) and "team_id" in row:
            # Some queries return a dict with team_id and total
            team_id_map[row["team_id"]] = row["total"]
        else:
            # Others are just a tuple with team_id and total
            team_id_map[int(row[0])] = row[1]
    return team_id_map


def _get_all_usage_data(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    """
    Gets all usage data for the specified period. Clickhouse is good at counting things so
    we count across all teams rather than doing it one by one
    """

    all_metrics = get_all_event_metrics_in_period(period_start, period_end)
    api_queries_usage = get_teams_with_api_queries_metrics(period_start, period_end)

    return {
        "teams_with_event_count_in_period": get_teams_with_billable_event_count_in_period(
            period_start, period_end, count_distinct=True
        ),
        "teams_with_enhanced_persons_event_count_in_period": get_teams_with_billable_enhanced_persons_event_count_in_period(
            period_start, period_end, count_distinct=True
        ),
        "teams_with_event_count_with_groups_in_period": get_teams_with_event_count_with_groups_in_period(
            period_start, period_end
        ),
        "teams_with_event_count_from_helicone_in_period": all_metrics["helicone_events"],
        "teams_with_event_count_from_langfuse_in_period": all_metrics["langfuse_events"],
        "teams_with_event_count_from_keywords_ai_in_period": all_metrics["keywords_ai_events"],
        "teams_with_event_count_from_traceloop_in_period": all_metrics["traceloop_events"],
        "teams_with_web_events_count_in_period": all_metrics["web_events"],
        "teams_with_web_lite_events_count_in_period": all_metrics["web_lite_events"],
        "teams_with_node_events_count_in_period": all_metrics["node_events"],
        "teams_with_android_events_count_in_period": all_metrics["android_events"],
        "teams_with_flutter_events_count_in_period": all_metrics["flutter_events"],
        "teams_with_ios_events_count_in_period": all_metrics["ios_events"],
        "teams_with_go_events_count_in_period": all_metrics["go_events"],
        "teams_with_java_events_count_in_period": all_metrics["java_events"],
        "teams_with_react_native_events_count_in_period": all_metrics["react_native_events"],
        "teams_with_ruby_events_count_in_period": all_metrics["ruby_events"],
        "teams_with_python_events_count_in_period": all_metrics["python_events"],
        "teams_with_php_events_count_in_period": all_metrics["php_events"],
        "teams_with_dotnet_events_count_in_period": all_metrics["dotnet_events"],
        "teams_with_elixir_events_count_in_period": all_metrics["elixir_events"],
        "teams_with_recording_count_in_period": get_teams_with_recording_count_in_period(
            period_start, period_end, snapshot_source="web"
        ),
        "teams_with_zero_duration_recording_count_in_period": get_teams_with_zero_duration_recording_count_in_period(
            period_start, period_end
        ),
        "teams_with_recording_bytes_in_period": get_teams_with_recording_bytes_in_period(
            period_start, period_end, snapshot_source="web"
        ),
        "teams_with_mobile_recording_count_in_period": get_teams_with_recording_count_in_period(
            period_start, period_end, snapshot_source="mobile"
        ),
        "teams_with_mobile_recording_bytes_in_period": get_teams_with_recording_bytes_in_period(
            period_start, period_end, snapshot_source="mobile"
        ),
        "teams_with_mobile_billable_recording_count_in_period": get_teams_with_mobile_billable_recording_count_in_period(
            period_start, period_end
        ),
        "teams_with_decide_requests_count_in_period": get_teams_with_feature_flag_requests_count_in_period(
            period_start, period_end, FlagRequestType.DECIDE
        ),
        "teams_with_local_evaluation_requests_count_in_period": get_teams_with_feature_flag_requests_count_in_period(
            period_start, period_end, FlagRequestType.LOCAL_EVALUATION
        ),
        "teams_with_group_types_total": list(
            GroupTypeMapping.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_dashboard_count": list(
            Dashboard.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_dashboard_template_count": list(
            Dashboard.objects.filter(creation_mode="template")
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        "teams_with_dashboard_shared_count": list(
            Dashboard.objects.filter(sharingconfiguration__enabled=True)
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        "teams_with_dashboard_tagged_count": list(
            Dashboard.objects.filter(tagged_items__isnull=False)
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        "teams_with_ff_count": list(
            FeatureFlag.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_ff_active_count": list(
            FeatureFlag.objects.filter(active=True).values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_issues_created_total": list(
            ErrorTrackingIssue.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_symbol_sets_count": list(
            ErrorTrackingSymbolSet.objects.values("team_id").annotate(total=Count("id")).order_by("team_id")
        ),
        "teams_with_resolved_symbol_sets_count": list(
            ErrorTrackingSymbolSet.objects.filter(storage_ptr__isnull=False)
            .values("team_id")
            .annotate(total=Count("id"))
            .order_by("team_id")
        ),
        "teams_with_query_app_bytes_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_bytes",
            access_method="",
        ),
        "teams_with_query_app_rows_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_rows",
            access_method="",
        ),
        "teams_with_query_app_duration_ms": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="query_duration_ms",
            access_method="",
        ),
        "teams_with_query_api_bytes_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_bytes",
            access_method="personal_api_key",
        ),
        "teams_with_query_api_rows_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_rows",
            access_method="personal_api_key",
        ),
        "teams_with_query_api_duration_ms": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="query_duration_ms",
            access_method="personal_api_key",
        ),
        "teams_with_api_queries_count": api_queries_usage["count"],
        "teams_with_api_queries_read_bytes": api_queries_usage["read_bytes"],
        "teams_with_event_explorer_app_bytes_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_bytes",
            query_types=["EventsQuery"],
            access_method="",
        ),
        "teams_with_event_explorer_app_rows_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_rows",
            query_types=["EventsQuery"],
            access_method="",
        ),
        "teams_with_event_explorer_app_duration_ms": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="query_duration_ms",
            query_types=["EventsQuery"],
            access_method="",
        ),
        "teams_with_event_explorer_api_bytes_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_bytes",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        ),
        "teams_with_event_explorer_api_rows_read": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="read_rows",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        ),
        "teams_with_event_explorer_api_duration_ms": get_teams_with_query_metric(
            period_start,
            period_end,
            metric="query_duration_ms",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        ),
        "teams_with_survey_responses_count_in_period": get_teams_with_survey_responses_count_in_period(
            period_start, period_end
        ),
        "teams_with_rows_synced_in_period": get_teams_with_rows_synced_in_period(period_start, period_end),
        "teams_with_free_historical_rows_synced_in_period": get_teams_with_free_historical_rows_synced_in_period(
            period_start, period_end
        ),
        "teams_with_rows_exported_in_period": get_teams_with_rows_exported_in_period(period_start, period_end),
        "teams_with_active_external_data_schemas_in_period": get_teams_with_active_external_data_schemas_in_period(),
        "teams_with_active_batch_exports_in_period": get_teams_with_active_batch_exports_in_period(),
        "teams_with_dwh_tables_storage_in_s3_in_mib": get_teams_with_dwh_tables_storage_in_s3(),
        "teams_with_dwh_mat_views_storage_in_s3_in_mib": get_teams_with_dwh_mat_views_storage_in_s3(),
        "teams_with_dwh_total_storage_in_s3_in_mib": get_teams_with_dwh_total_storage_in_s3(),
        "teams_with_exceptions_captured_in_period": get_teams_with_exceptions_captured_in_period(
            period_start, period_end
        ),
        "teams_with_hog_function_calls_in_period": get_teams_with_hog_function_calls_in_period(
            period_start, period_end
        ),
        "teams_with_hog_function_fetch_calls_in_period": get_teams_with_hog_function_fetch_calls_in_period(
            period_start, period_end
        ),
        "teams_with_cdp_billable_invocations_in_period": get_teams_with_cdp_billable_invocations_in_period(
            period_start, period_end
        ),
        "teams_with_ai_event_count_in_period": get_teams_with_ai_event_count_in_period(period_start, period_end),
        "teams_with_active_hog_destinations_in_period": get_teams_with_active_hog_destinations_in_period(),
        "teams_with_active_hog_transformations_in_period": get_teams_with_active_hog_transformations_in_period(),
    }


def _get_all_usage_data_as_team_rows(period_start: datetime, period_end: datetime) -> dict[str, Any]:
    """
    Gets all usage data for the specified period as a map of team_id -> value. This makes it faster
    to access the data than looping over all_data to find what we want.
    """
    all_data = _get_all_usage_data(period_start, period_end)
    # convert it to a map of team_id -> value
    for key, rows in all_data.items():
        all_data[key] = convert_team_usage_rows_to_dict(rows)
    return all_data


def _get_teams_for_usage_reports() -> Sequence[Team]:
    return list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )


def _get_team_report(all_data: dict[str, Any], team: Team) -> UsageReportCounters:
    decide_requests_count_in_period = all_data["teams_with_decide_requests_count_in_period"].get(team.id, 0)
    local_evaluation_requests_count_in_period = all_data["teams_with_local_evaluation_requests_count_in_period"].get(
        team.id, 0
    )
    return UsageReportCounters(
        event_count_in_period=all_data["teams_with_event_count_in_period"].get(team.id, 0),
        enhanced_persons_event_count_in_period=all_data["teams_with_enhanced_persons_event_count_in_period"].get(
            team.id, 0
        ),
        event_count_with_groups_in_period=all_data["teams_with_event_count_with_groups_in_period"].get(team.id, 0),
        event_count_from_langfuse_in_period=all_data["teams_with_event_count_from_langfuse_in_period"].get(team.id, 0),
        event_count_from_traceloop_in_period=all_data["teams_with_event_count_from_traceloop_in_period"].get(
            team.id, 0
        ),
        event_count_from_helicone_in_period=all_data["teams_with_event_count_from_helicone_in_period"].get(team.id, 0),
        event_count_from_keywords_ai_in_period=all_data["teams_with_event_count_from_keywords_ai_in_period"].get(
            team.id, 0
        ),
        recording_count_in_period=all_data["teams_with_recording_count_in_period"].get(team.id, 0),
        recording_bytes_in_period=all_data["teams_with_recording_bytes_in_period"].get(team.id, 0),
        zero_duration_recording_count_in_period=all_data["teams_with_zero_duration_recording_count_in_period"].get(
            team.id, 0
        ),
        mobile_recording_count_in_period=all_data["teams_with_mobile_recording_count_in_period"].get(team.id, 0),
        mobile_recording_bytes_in_period=all_data["teams_with_mobile_recording_bytes_in_period"].get(team.id, 0),
        mobile_billable_recording_count_in_period=all_data["teams_with_mobile_billable_recording_count_in_period"].get(
            team.id, 0
        ),
        group_types_total=all_data["teams_with_group_types_total"].get(team.id, 0),
        decide_requests_count_in_period=decide_requests_count_in_period,
        local_evaluation_requests_count_in_period=local_evaluation_requests_count_in_period,
        billable_feature_flag_requests_count_in_period=decide_requests_count_in_period
        + (local_evaluation_requests_count_in_period * 10),
        dashboard_count=all_data["teams_with_dashboard_count"].get(team.id, 0),
        dashboard_template_count=all_data["teams_with_dashboard_template_count"].get(team.id, 0),
        dashboard_shared_count=all_data["teams_with_dashboard_shared_count"].get(team.id, 0),
        dashboard_tagged_count=all_data["teams_with_dashboard_tagged_count"].get(team.id, 0),
        ff_count=all_data["teams_with_ff_count"].get(team.id, 0),
        ff_active_count=all_data["teams_with_ff_active_count"].get(team.id, 0),
        query_app_bytes_read=all_data["teams_with_query_app_bytes_read"].get(team.id, 0),
        query_app_rows_read=all_data["teams_with_query_app_rows_read"].get(team.id, 0),
        query_app_duration_ms=all_data["teams_with_query_app_duration_ms"].get(team.id, 0),
        query_api_bytes_read=all_data["teams_with_query_api_bytes_read"].get(team.id, 0),
        query_api_rows_read=all_data["teams_with_query_api_rows_read"].get(team.id, 0),
        query_api_duration_ms=all_data["teams_with_query_api_duration_ms"].get(team.id, 0),
        api_queries_query_count=all_data["teams_with_api_queries_count"].get(team.id, 0),
        api_queries_bytes_read=all_data["teams_with_api_queries_read_bytes"].get(team.id, 0),
        event_explorer_app_bytes_read=all_data["teams_with_event_explorer_app_bytes_read"].get(team.id, 0),
        event_explorer_app_rows_read=all_data["teams_with_event_explorer_app_rows_read"].get(team.id, 0),
        event_explorer_app_duration_ms=all_data["teams_with_event_explorer_app_duration_ms"].get(team.id, 0),
        event_explorer_api_bytes_read=all_data["teams_with_event_explorer_api_bytes_read"].get(team.id, 0),
        event_explorer_api_rows_read=all_data["teams_with_event_explorer_api_rows_read"].get(team.id, 0),
        event_explorer_api_duration_ms=all_data["teams_with_event_explorer_api_duration_ms"].get(team.id, 0),
        survey_responses_count_in_period=all_data["teams_with_survey_responses_count_in_period"].get(team.id, 0),
        rows_synced_in_period=all_data["teams_with_rows_synced_in_period"].get(team.id, 0),
        free_historical_rows_synced_in_period=all_data["teams_with_free_historical_rows_synced_in_period"].get(
            team.id, 0
        ),
        rows_exported_in_period=all_data["teams_with_rows_exported_in_period"].get(team.id, 0),
        active_external_data_schemas_in_period=all_data["teams_with_active_external_data_schemas_in_period"].get(
            team.id, 0
        ),
        active_batch_exports_in_period=all_data["teams_with_active_batch_exports_in_period"].get(team.id, 0),
        dwh_total_storage_in_s3_in_mib=all_data["teams_with_dwh_total_storage_in_s3_in_mib"].get(team.id, 0),
        dwh_tables_storage_in_s3_in_mib=all_data["teams_with_dwh_tables_storage_in_s3_in_mib"].get(team.id, 0),
        dwh_mat_views_storage_in_s3_in_mib=all_data["teams_with_dwh_mat_views_storage_in_s3_in_mib"].get(team.id, 0),
        issues_created_total=all_data["teams_with_issues_created_total"].get(team.id, 0),
        symbol_sets_count=all_data["teams_with_symbol_sets_count"].get(team.id, 0),
        resolved_symbol_sets_count=all_data["teams_with_resolved_symbol_sets_count"].get(team.id, 0),
        hog_function_calls_in_period=all_data["teams_with_hog_function_calls_in_period"].get(team.id, 0),
        hog_function_fetch_calls_in_period=all_data["teams_with_hog_function_fetch_calls_in_period"].get(team.id, 0),
        cdp_billable_invocations_in_period=all_data["teams_with_cdp_billable_invocations_in_period"].get(team.id, 0),
        web_events_count_in_period=all_data["teams_with_web_events_count_in_period"].get(team.id, 0),
        web_lite_events_count_in_period=all_data["teams_with_web_lite_events_count_in_period"].get(team.id, 0),
        node_events_count_in_period=all_data["teams_with_node_events_count_in_period"].get(team.id, 0),
        android_events_count_in_period=all_data["teams_with_android_events_count_in_period"].get(team.id, 0),
        flutter_events_count_in_period=all_data["teams_with_flutter_events_count_in_period"].get(team.id, 0),
        ios_events_count_in_period=all_data["teams_with_ios_events_count_in_period"].get(team.id, 0),
        go_events_count_in_period=all_data["teams_with_go_events_count_in_period"].get(team.id, 0),
        java_events_count_in_period=all_data["teams_with_java_events_count_in_period"].get(team.id, 0),
        react_native_events_count_in_period=all_data["teams_with_react_native_events_count_in_period"].get(team.id, 0),
        ruby_events_count_in_period=all_data["teams_with_ruby_events_count_in_period"].get(team.id, 0),
        python_events_count_in_period=all_data["teams_with_python_events_count_in_period"].get(team.id, 0),
        php_events_count_in_period=all_data["teams_with_php_events_count_in_period"].get(team.id, 0),
        dotnet_events_count_in_period=all_data["teams_with_dotnet_events_count_in_period"].get(team.id, 0),
        elixir_events_count_in_period=all_data["teams_with_elixir_events_count_in_period"].get(team.id, 0),
        exceptions_captured_in_period=all_data["teams_with_exceptions_captured_in_period"].get(team.id, 0),
        ai_event_count_in_period=all_data["teams_with_ai_event_count_in_period"].get(team.id, 0),
        active_hog_destinations_in_period=all_data["teams_with_active_hog_destinations_in_period"].get(team.id, 0),
        active_hog_transformations_in_period=all_data["teams_with_active_hog_transformations_in_period"].get(
            team.id, 0
        ),
    )


def _add_team_report_to_org_reports(
    org_reports: dict[str, OrgReport],
    team: Team,
    team_report: UsageReportCounters,
    period_start: datetime,
) -> None:
    org_id = str(team.organization.id)
    if org_id not in org_reports:
        org_report = OrgReport(
            date=period_start.strftime("%Y-%m-%d"),
            organization_id=org_id,
            organization_name=team.organization.name,
            organization_created_at=team.organization.created_at.isoformat(),
            organization_user_count=get_org_user_count(org_id),
            team_count=1,
            teams={str(team.id): team_report},
            **dataclasses.asdict(team_report),  # Clone the team report as the basis
        )
        org_reports[org_id] = org_report
    else:
        org_report = org_reports[org_id]
        org_report.teams[str(team.id)] = team_report
        org_report.team_count += 1

        # Iterate on all fields of the UsageReportCounters and add the values from the team report to the org report
        for field in dataclasses.fields(UsageReportCounters):
            if hasattr(team_report, field.name):
                setattr(
                    org_report,
                    field.name,
                    getattr(org_report, field.name) + getattr(team_report, field.name),
                )


def _get_all_org_reports(period_start: datetime, period_end: datetime) -> dict[str, OrgReport]:
    logger.info("Querying all org reports", period_start=period_start, period_end=period_end)

    all_data = _get_all_usage_data_as_team_rows(period_start, period_end)

    logger.info("Querying all teams")

    teams = _get_teams_for_usage_reports()

    logger.info("Querying all teams complete", teams_count=len(teams))

    org_reports: dict[str, OrgReport] = {}

    logger.info("Generating org reports")

    for team in teams:
        team_report = _get_team_report(all_data, team)
        _add_team_report_to_org_reports(org_reports, team, team_report, period_start)

    logger.info("Generating org reports complete", org_reports_count=len(org_reports))

    return org_reports


def _get_full_org_usage_report(org_report: OrgReport, instance_metadata: InstanceMetadata) -> FullUsageReport:
    return FullUsageReport(
        **dataclasses.asdict(org_report),
        **dataclasses.asdict(instance_metadata),
    )


def _get_full_org_usage_report_as_dict(full_report: FullUsageReport) -> dict[str, Any]:
    return dataclasses.asdict(full_report)


def _queue_report(producer: Any, organization_id: str, full_report_dict: dict[str, Any]) -> None:
    json_data = json.dumps(
        {"organization_id": organization_id, "usage_report": full_report_dict}, separators=(",", ":")
    )
    compressed_bytes = gzip.compress(json_data.encode("utf-8"))
    compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")

    message_attributes = {
        "content_encoding": "gzip",
        "content_type": "application/json",
    }

    response = producer.send_message(message_body=compressed_b64, message_attributes=message_attributes)

    if not response:
        logger.exception(f"Failed to send usage report for organization {organization_id}")

    return


@shared_task(**USAGE_REPORT_TASK_KWARGS, max_retries=3)
def send_all_org_usage_reports(
    dry_run: bool = False,
    at: Optional[str] = None,
    skip_capture_event: bool = False,
    organization_ids: Optional[list[str]] = None,
) -> None:
    import posthoganalytics

    are_usage_reports_disabled = posthoganalytics.feature_enabled("disable-usage-reports", "internal_billing_events")
    if are_usage_reports_disabled:
        posthoganalytics.capture_exception(Exception(f"Usage reports are disabled for {at}"))
        return

    at_date = parser.parse(at) if at else None
    period = get_previous_day(at=at_date)
    period_start, period_end = period

    instance_metadata = get_instance_metadata(period)

    producer = None
    try:
        if settings.EE_AVAILABLE:
            from products.enterprise.backend.sqs.SQSProducer import get_sqs_producer

            producer = get_sqs_producer("usage_reports")
    except Exception:
        pass

    pha_client = get_ph_client(sync_mode=True)

    if organization_ids:
        logger.info(
            "Sending usage reports for specific organizations",
            org_count=len(organization_ids),
            organization_ids=organization_ids,
        )

    logger.info("Querying usage report data")
    query_time_start = datetime.now()

    org_reports = _get_all_org_reports(period_start, period_end)

    if organization_ids:
        original_count = len(org_reports)
        org_reports = {org_id: report for org_id, report in org_reports.items() if org_id in organization_ids}
        filtered_count = len(org_reports)
        missing_orgs = set(organization_ids) - set(org_reports.keys())
        logger.info(
            f"Filtered org reports from {original_count} to {filtered_count} organizations",
            requested_org_count=len(organization_ids),
            found_org_count=filtered_count,
            missing_orgs=missing_orgs or None,
        )

    filtering_properties: dict[str, Any] = {"filtered": organization_ids is not None}
    if organization_ids:
        filtering_properties["requested_org_count"] = len(organization_ids)
        filtering_properties["requested_missing_org_count"] = len(missing_orgs) if missing_orgs else None

    query_time_duration = (datetime.now() - query_time_start).total_seconds()
    logger.info(f"Found {len(org_reports)} org reports. It took {query_time_duration} seconds.")

    total_orgs = len(org_reports)
    total_orgs_sent = 0

    logger.info("Sending usage reports to billing")
    queue_time_start = datetime.now()

    pha_client.capture(
        distinct_id="internal_billing_events",
        event="usage reports starting",
        properties={
            "total_orgs": total_orgs,
            "region": get_instance_region(),
            **filtering_properties,
        },
        groups={"instance": settings.SITE_URL},
    )

    for org_report in org_reports.values():
        try:
            organization_id = org_report.organization_id

            full_report = _get_full_org_usage_report(org_report, instance_metadata)
            full_report_dict = _get_full_org_usage_report_as_dict(full_report)

            if dry_run:
                logger.info(f"Dry run, skipping sending for organization {organization_id}")
                continue

            # First capture the events to PostHog
            if not skip_capture_event:
                try:
                    at_date_str = at_date.isoformat() if at_date else None
                    capture_report.delay(
                        organization_id=organization_id,
                        full_report_dict=full_report_dict,
                        at_date=at_date_str,
                    )
                except Exception as capture_err:
                    logger.exception(f"Failed to capture report for organization {organization_id}", error=capture_err)

            # Then send the reports to billing through SQS (only if the producer is available)
            if has_non_zero_usage(full_report) and producer:
                try:
                    _queue_report(producer, organization_id, full_report_dict)
                    total_orgs_sent += 1
                except Exception as err:
                    logger.exception(f"Failed to queue report for organization {organization_id}", error=err)

        except Exception as loop_err:
            logger.exception(f"Failed to process organization {organization_id}", error=loop_err)

    queue_time_duration = (datetime.now() - queue_time_start).total_seconds()
    pha_client.capture(
        distinct_id="internal_billing_events",
        event="usage reports complete",
        properties={
            "total_orgs": total_orgs,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_orgs_sent": total_orgs_sent,
            "query_time": query_time_duration,
            "queue_time": queue_time_duration,
            "total_time": query_time_duration + queue_time_duration,
            "region": get_instance_region(),
            **filtering_properties,
        },
        groups={"instance": settings.SITE_URL},
    )

    logger.info(f"Usage reports complete. Total orgs: {total_orgs}, total orgs sent: {total_orgs_sent}.")
