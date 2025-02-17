import dataclasses
from datetime import datetime, timedelta
from typing import Optional, Tuple
import uuid

from dagster import (
    Config,
    MaterializeResult,
    asset,
    AssetExecutionContext,
    MetadataValue,
)
from posthog.models.team.team import Team
from posthog.models.organization import OrganizationMembership
from posthog.tasks.usage_report import (
    get_teams_with_billable_event_count_in_period,
    get_instance_metadata,
    _add_team_report_to_org_reports,
    get_teams_with_billable_enhanced_persons_event_count_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_feature_flag_requests_count_in_period,
    get_all_event_metrics_in_period,
    get_teams_with_query_metric,
    get_teams_with_survey_responses_count_in_period,
    get_teams_with_rows_synced_in_period,
    get_teams_with_hog_function_calls_in_period,
    get_teams_with_hog_function_fetch_calls_in_period,
    get_teams_with_event_count_with_groups_in_period,
    FullUsageReport,
    InstanceMetadata,
    OrganizationReport,
    UsageReportCounters,
    FlagRequestType,
    Dashboard,
    Count,
    GroupTypeMapping,
    FeatureFlag,
)
from clickhouse_driver.client import Client
from django.conf import settings
from django.db.models import Q

# ------------------------------------------------------------------------------
# Configuration and helper functions
# ------------------------------------------------------------------------------

class UsageReportConfig(Config):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    dry_run: bool = False

def get_period(config: UsageReportConfig) -> Tuple[datetime, datetime]:
    """Return a tuple (period_start, period_end) based on the config.
    
    Defaults to yesterday if start_date is not provided.
    """
    if config.end_date:
        period_end = datetime.fromisoformat(config.end_date)
    else:
        period_end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if config.start_date:
        period_start = datetime.fromisoformat(config.start_date)
    else:
        period_start = period_end - timedelta(days=1)
    return period_start, period_end

def get_client() -> Client:
    return Client(
        host=settings.CLICKHOUSE_HOST,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
        verify=settings.CLICKHOUSE_VERIFY,
    )

def get_cluster() -> str:
    return settings.CLICKHOUSE_CLUSTER

def get_table_name() -> str:
    return "usage_report_data"

def zk_path(table_name: str) -> str:
    ns_uuid = uuid.uuid4()
    testing = f"testing/{ns_uuid}/" if settings.TEST else ""
    return f"/clickhouse/tables/{testing}noshard/{table_name}"

# ------------------------------------------------------------------------------
# Assets for table creation
# ------------------------------------------------------------------------------

@asset
def create_usage_report_table():
    """
    Create a table to store the usage report data (only if the table does not exist).
    
    Structure:
    - query: The query key (e.g. "teams_with_event_count_in_period")
    - team_id: The team that the query was run for
    - count: The number of events returned by the query
    - period_start: The start of the period for which the query was run
    - period_end: The end of the period for which the query was run
    - created_at: The time the query was run

    Note: there is not currently a unique constraint so we can re-run usage reports multiple times for a day
    and it will just pull the latest value for the team, period, and query.
    """
    client = get_client()
    table = get_table_name()
    client.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} ON CLUSTER '{get_cluster()}'
        (
            query String,
            team_id Int64,
            count Int64,
            period_start DateTime,
            period_end DateTime,
            created_at DateTime DEFAULT now()
        )
        ENGINE = ReplicatedMergeTree('{zk_path(table)}', '{{replica}}')
        ORDER BY (team_id, period_start, period_end, query)
    """)

# ------------------------------------------------------------------------------
# Functions that query Django ORM
# ------------------------------------------------------------------------------

def get_all_teams():
    """
    Get all teams that are not for internal metrics or demo teams.

    Not an asset - loaded into memory.
    """
    return list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "name", "organization__id", "organization__name", "organization__created_at")
    )

def get_organization_user_count(organization_id: str) -> int:
    """
    Get the number of users in an organization.

    Not an asset - loaded into memory.
    """
    return OrganizationMembership.objects.filter(organization_id=organization_id).count()

# ------------------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------------------

def build_full_usage_report(organization_report: OrganizationReport, instance_metadata: InstanceMetadata) -> FullUsageReport:
    return FullUsageReport(
        **dataclasses.asdict(organization_report),
        **dataclasses.asdict(instance_metadata),
    )

# ------------------------------------------------------------------------------
# Assets that execute queries and insert data into tables
# ------------------------------------------------------------------------------

@asset(deps=[create_usage_report_table])
def query_event_counts(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """
    Query the event counts for all teams in the period and store in the usage report table.
    No need to return the data since it's stored in the table.
    """
    period_start, period_end = get_period(config)
    results = get_teams_with_billable_event_count_in_period(period_start, period_end)

    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_event_count_in_period', team_id, count, period_start, period_end) for team_id, count in results],
    )

@asset(deps=[create_usage_report_table])
def query_event_metrics(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query all event-related metrics and store in the usage report table."""
    period_start, period_end = get_period(config)
    all_metrics = get_all_event_metrics_in_period(period_start, period_end)
    
    client = get_client()
    data = []
    
    # Add entries for each metric type
    for metric_name, results in all_metrics.items():
        query_key = f"teams_with_{metric_name}"
        for team_id, count in results:
            data.append((query_key, team_id, count, period_start, period_end))
    
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_enhanced_persons_events(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query enhanced persons event counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    results = get_teams_with_billable_enhanced_persons_event_count_in_period(period_start, period_end, count_distinct=True)

    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_enhanced_persons_event_count_in_period', team_id, count, period_start, period_end) for team_id, count in results]
    )

@asset(deps=[create_usage_report_table])
def query_recording_counts(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query recording counts for web and mobile and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    web_results = get_teams_with_recording_count_in_period(period_start, period_end, snapshot_source="web")
    mobile_results = get_teams_with_recording_count_in_period(period_start, period_end, snapshot_source="mobile")

    client = get_client()
    data = []
    
    for team_id, count in web_results:
        data.append(('teams_with_recording_count_in_period', team_id, count, period_start, period_end))
    
    for team_id, count in mobile_results:
        data.append(('teams_with_mobile_recording_count_in_period', team_id, count, period_start, period_end))

    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_feature_flag_requests(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query feature flag request counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    decide_results = get_teams_with_feature_flag_requests_count_in_period(period_start, period_end, FlagRequestType.DECIDE)
    local_eval_results = get_teams_with_feature_flag_requests_count_in_period(period_start, period_end, FlagRequestType.LOCAL_EVALUATION)

    client = get_client()
    data = []
    
    for team_id, count in decide_results:
        data.append(('teams_with_decide_requests_count_in_period', team_id, count, period_start, period_end))
    
    for team_id, count in local_eval_results:
        data.append(('teams_with_local_evaluation_requests_count_in_period', team_id, count, period_start, period_end))

    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_dashboard_metrics(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query dashboard-related metrics and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    metrics = {
        'teams_with_dashboard_count': Dashboard.objects.values('team_id').annotate(total=Count('id')),
        'teams_with_dashboard_template_count': Dashboard.objects.filter(creation_mode='template').values('team_id').annotate(total=Count('id')),
        'teams_with_dashboard_shared_count': Dashboard.objects.filter(sharingconfiguration__enabled=True).values('team_id').annotate(total=Count('id')),
        'teams_with_dashboard_tagged_count': Dashboard.objects.filter(tagged_items__isnull=False).values('team_id').annotate(total=Count('id')),
    }

    client = get_client()
    data = []
    
    for metric_name, queryset in metrics.items():
        for result in queryset:
            data.append((metric_name, result['team_id'], result['total'], period_start, period_end))

    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_query_metrics(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """
    Query all query-related metrics for both app and API usage and store in the usage report table.
    This includes:
    1. General query metrics (app and API)
    2. Event explorer specific metrics (app and API)
    Each category tracks:
    - read_bytes
    - read_rows
    - query_duration_ms
    """
    period_start, period_end = get_period(config)
    client = get_client()
    data = []

    # 1. General Query Metrics
    # 1a. App queries (no access method)
    app_metrics = [
        ("teams_with_query_app_bytes_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_bytes",
            access_method="",
        )),
        ("teams_with_query_app_rows_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_rows",
            access_method="",
        )),
        ("teams_with_query_app_duration_ms", get_teams_with_query_metric(
            period_start, period_end,
            metric="query_duration_ms",
            access_method="",
        )),
    ]

    # 1b. API queries (using personal_api_key)
    api_metrics = [
        ("teams_with_query_api_bytes_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_bytes",
            access_method="personal_api_key",
        )),
        ("teams_with_query_api_rows_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_rows",
            access_method="personal_api_key",
        )),
        ("teams_with_query_api_duration_ms", get_teams_with_query_metric(
            period_start, period_end,
            metric="query_duration_ms",
            access_method="personal_api_key",
        )),
    ]

    # 2. Event Explorer Specific Metrics
    # 2a. Event Explorer App queries
    event_explorer_app_metrics = [
        ("teams_with_event_explorer_app_bytes_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_bytes",
            query_types=["EventsQuery"],
            access_method="",
        )),
        ("teams_with_event_explorer_app_rows_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_rows",
            query_types=["EventsQuery"],
            access_method="",
        )),
        ("teams_with_event_explorer_app_duration_ms", get_teams_with_query_metric(
            period_start, period_end,
            metric="query_duration_ms",
            query_types=["EventsQuery"],
            access_method="",
        )),
    ]

    # 2b. Event Explorer API queries
    event_explorer_api_metrics = [
        ("teams_with_event_explorer_api_bytes_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_bytes",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        )),
        ("teams_with_event_explorer_api_rows_read", get_teams_with_query_metric(
            period_start, period_end,
            metric="read_rows",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        )),
        ("teams_with_event_explorer_api_duration_ms", get_teams_with_query_metric(
            period_start, period_end,
            metric="query_duration_ms",
            query_types=["EventsQuery"],
            access_method="personal_api_key",
        )),
    ]

    # Combine all metrics
    all_metrics = app_metrics + api_metrics + event_explorer_app_metrics + event_explorer_api_metrics

    # Format data for insertion
    for metric_name, results in all_metrics:
        for team_id, count in results:
            data.append((metric_name, team_id, count, period_start, period_end))

    # Insert all metrics in a single query
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_group_types(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query group types metrics and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    results = GroupTypeMapping.objects.values('team_id').annotate(total=Count('id'))
    
    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_group_types_total', result['team_id'], result['total'], period_start, period_end) 
         for result in results]
    )

@asset(deps=[create_usage_report_table])
def query_feature_flags(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query feature flag counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    total_results = FeatureFlag.objects.values('team_id').annotate(total=Count('id'))
    active_results = FeatureFlag.objects.filter(active=True).values('team_id').annotate(total=Count('id'))
    
    client = get_client()
    data = []
    
    for result in total_results:
        data.append(('teams_with_ff_count', result['team_id'], result['total'], period_start, period_end))
    
    for result in active_results:
        data.append(('teams_with_ff_active_count', result['team_id'], result['total'], period_start, period_end))

    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_survey_responses(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query survey response counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_survey_responses_count_in_period(period_start, period_end)
    
    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_survey_responses_count_in_period', team_id, count, period_start, period_end) 
         for team_id, count in results]
    )

@asset(deps=[create_usage_report_table])
def query_rows_synced(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query rows synced counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_rows_synced_in_period(period_start, period_end)
    
    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_rows_synced_in_period', team_id, count, period_start, period_end) 
         for team_id, count in results]
    )

@asset(deps=[create_usage_report_table])
def query_hog_functions(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query HogQL function calls and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    calls_results = get_teams_with_hog_function_calls_in_period(period_start, period_end)
    fetch_results = get_teams_with_hog_function_fetch_calls_in_period(period_start, period_end)
    
    client = get_client()
    data = []
    
    for team_id, count in calls_results:
        data.append(('teams_with_hog_function_calls_in_period', team_id, count, period_start, period_end))
    
    for team_id, count in fetch_results:
        data.append(('teams_with_hog_function_fetch_calls_in_period', team_id, count, period_start, period_end))

    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        data
    )

@asset(deps=[create_usage_report_table])
def query_events_with_groups(context: AssetExecutionContext, config: UsageReportConfig) -> None:
    """Query events with groups counts and store in the usage report table."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_event_count_with_groups_in_period(period_start, period_end)
    
    client = get_client()
    client.execute(
        f"""
        INSERT INTO {get_table_name()} (query, team_id, count, period_start, period_end)
        VALUES
        """,
        [('teams_with_event_count_with_groups_in_period', team_id, count, period_start, period_end) 
         for team_id, count in results]
    )

def get_team_report(team_id: int, period_start: datetime, period_end: datetime) -> UsageReportCounters:
    """
    Query the usage report table to build a team report for a specific period.
    """
    client = get_client()
    result = client.execute(f"""
        SELECT DISTINCT ON (query)
            query, count
        FROM {get_table_name()}
        WHERE team_id = %(team_id)s
            AND period_start = %(period_start)s
            AND period_end = %(period_end)s
        ORDER BY query, created_at DESC
    """, {
        'team_id': team_id,
        'period_start': period_start,
        'period_end': period_end,
    })
    
    counts_by_query = {query: count for query, count in result}
    
    return UsageReportCounters(
        # Product analytics
        event_count_in_period=counts_by_query.get('teams_with_event_count_in_period', 0),
        enhanced_persons_event_count_in_period=counts_by_query.get('teams_with_enhanced_persons_event_count_in_period', 0),
        event_count_with_groups_in_period=counts_by_query.get('teams_with_event_count_with_groups_in_period', 0),
        event_count_from_langfuse_in_period=counts_by_query.get('teams_with_event_count_from_langfuse_in_period', 0),
        event_count_from_traceloop_in_period=counts_by_query.get('teams_with_event_count_from_traceloop_in_period', 0),
        event_count_from_helicone_in_period=counts_by_query.get('teams_with_event_count_from_helicone_in_period', 0),
        event_count_from_keywords_ai_in_period=counts_by_query.get('teams_with_event_count_from_keywords_ai_in_period', 0),
        
        # Product analytics - SDKs
        node_events_count_in_period=counts_by_query.get('teams_with_node_events_count_in_period', 0),
        android_events_count_in_period=counts_by_query.get('teams_with_android_events_count_in_period', 0),
        flutter_events_count_in_period=counts_by_query.get('teams_with_flutter_events_count_in_period', 0),
        ios_events_count_in_period=counts_by_query.get('teams_with_ios_events_count_in_period', 0),
        go_events_count_in_period=counts_by_query.get('teams_with_go_events_count_in_period', 0),
        java_events_count_in_period=counts_by_query.get('teams_with_java_events_count_in_period', 0),
        react_native_events_count_in_period=counts_by_query.get('teams_with_react_native_events_count_in_period', 0),
        ruby_events_count_in_period=counts_by_query.get('teams_with_ruby_events_count_in_period', 0),
        python_events_count_in_period=counts_by_query.get('teams_with_python_events_count_in_period', 0),
        php_events_count_in_period=counts_by_query.get('teams_with_php_events_count_in_period', 0),
        
        # Session replays
        recording_count_in_period=counts_by_query.get('teams_with_recording_count_in_period', 0),
        mobile_recording_count_in_period=counts_by_query.get('teams_with_mobile_recording_count_in_period', 0),
        
        # Feature flags
        decide_requests_count_in_period=counts_by_query.get('teams_with_decide_requests_count_in_period', 0),
        local_evaluation_requests_count_in_period=counts_by_query.get('teams_with_local_evaluation_requests_count_in_period', 0),
        billable_feature_flag_requests_count_in_period=(
            counts_by_query.get('teams_with_decide_requests_count_in_period', 0) +
            (counts_by_query.get('teams_with_local_evaluation_requests_count_in_period', 0) * 10)
        ),
        ff_count=counts_by_query.get('teams_with_ff_count', 0),
        ff_active_count=counts_by_query.get('teams_with_ff_active_count', 0),

        # Dashboards
        dashboard_count=counts_by_query.get('teams_with_dashboard_count', 0),
        dashboard_template_count=counts_by_query.get('teams_with_dashboard_template_count', 0),
        dashboard_shared_count=counts_by_query.get('teams_with_dashboard_shared_count', 0),
        dashboard_tagged_count=counts_by_query.get('teams_with_dashboard_tagged_count', 0),
        
        # Surveys
        survey_responses_count_in_period=counts_by_query.get('teams_with_survey_responses_count_in_period', 0),
        
        # Data warehouse
        rows_synced_in_period=counts_by_query.get('teams_with_rows_synced_in_period', 0),
        
        # Hog functions        
        hog_function_calls_in_period=counts_by_query.get('teams_with_hog_function_calls_in_period', 0),
        hog_function_fetch_calls_in_period=counts_by_query.get('teams_with_hog_function_fetch_calls_in_period', 0),
        
        # Web analytics
        web_events_count_in_period=counts_by_query.get('teams_with_web_events_count_in_period', 0),
        web_lite_events_count_in_period=counts_by_query.get('teams_with_web_lite_events_count_in_period', 0),
        
        # API / misc
        query_app_bytes_read=counts_by_query.get('teams_with_query_app_bytes_read', 0),
        query_app_rows_read=counts_by_query.get('teams_with_query_app_rows_read', 0),
        query_app_duration_ms=counts_by_query.get('teams_with_query_app_duration_ms', 0),
        query_api_bytes_read=counts_by_query.get('teams_with_query_api_bytes_read', 0),
        query_api_rows_read=counts_by_query.get('teams_with_query_api_rows_read', 0),
        query_api_duration_ms=counts_by_query.get('teams_with_query_api_duration_ms', 0),
        event_explorer_app_bytes_read=counts_by_query.get('teams_with_event_explorer_app_bytes_read', 0),
        event_explorer_app_rows_read=counts_by_query.get('teams_with_event_explorer_app_rows_read', 0),
        event_explorer_app_duration_ms=counts_by_query.get('teams_with_event_explorer_app_duration_ms', 0),
        event_explorer_api_bytes_read=counts_by_query.get('teams_with_event_explorer_api_bytes_read', 0),
        event_explorer_api_rows_read=counts_by_query.get('teams_with_event_explorer_api_rows_read', 0),
        event_explorer_api_duration_ms=counts_by_query.get('teams_with_event_explorer_api_duration_ms', 0),
        group_types_total=counts_by_query.get('teams_with_group_types_total', 0),
    )

# ------------------------------------------------------------------------------
# Final Asset to Generate and Send the Usage Report
# ------------------------------------------------------------------------------

@asset(
    deps=[
        query_event_counts,
        query_event_metrics,
        query_enhanced_persons_events,
        query_recording_counts,
        query_feature_flag_requests,
        query_dashboard_metrics,
        query_query_metrics,
        query_group_types,
        query_feature_flags,
        query_survey_responses,
        query_rows_synced,
        query_hog_functions,
        query_events_with_groups,
    ]
)
def generate_usage_report(
    context: AssetExecutionContext,
    config: UsageReportConfig,
) -> MaterializeResult:
    """
    Aggregate all query results into per-team usage reports and send them to the billing service.
    """
    period_start, period_end = get_period(config)
    context.log.info(f"Period start: {period_start} and end: {period_end}")
    
    # Load all teams from Postgres into memory
    teams = get_all_teams()
    context.log.info(f"Found {len(teams)} teams")

    # Get the instance metadata
    instance_metadata = get_instance_metadata((period_start, period_end))

    # Initialize a dictionary to store the org reports
    organizations_reports: dict[str, OrganizationReport] = {}

    # Things to notes:
    # - We don't yet set up the disable-usage-reports feature flag
    # - All teams are loaded into memory
    # - All teams are processed synchronously so if one fails all fail, we need to batch these so they are processed in parallel and recoverable from failures
    # - Same goes for looping over organizations and sending the report to the billing service
    # - capture_report is not yet set up
    
    # Iterate over all teams and add their report to organizations_reports
    for team in teams:
        context.log.info(f"Processing team {team.id}")
        team_report = get_team_report(team.id, period_start, period_end)
        _add_team_report_to_org_reports(organizations_reports, team, team_report, period_start)

    # Iterate over all organizations and send their report to the billing service
    for organization_report in organizations_reports.values():
        full_report = build_full_usage_report(organization_report, instance_metadata)
        context.log.info(f"Processing organization {organization_report.organization_id}")
        context.log.info(f"Organization report: {full_report}")
        # TODO: uncomment this when we are ready to move to production
        # send_report_to_billing_service.delay(str(organization_report.organization_id), organization_report)
    
    return MaterializeResult(
        metadata={
            "teams_processed": MetadataValue.int(len(teams)),
            "organizations_processed": MetadataValue.int(len(organizations_reports)),
            "period_start": MetadataValue.text(period_start.isoformat()),
            "period_end": MetadataValue.text(period_end.isoformat()),
        }
    )

