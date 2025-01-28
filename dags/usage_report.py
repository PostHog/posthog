import dataclasses
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from dagster import (
    Config,
    MaterializeResult,
    asset,
    AssetExecutionContext,
    MetadataValue,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.team.team import Team
from posthog.tasks.usage_report import (
    get_teams_with_billable_event_count_in_period,
    get_teams_with_billable_enhanced_persons_event_count_in_period,
    get_teams_with_event_count_with_groups_in_period,
    get_all_event_metrics_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_query_metric,
    get_teams_with_feature_flag_requests_count_in_period,
    get_teams_with_survey_responses_count_in_period,
    get_teams_with_rows_synced_in_period,
    get_teams_with_hog_function_calls_in_period,
    get_teams_with_hog_function_fetch_calls_in_period,
    get_instance_metadata,
    send_report_to_billing_service,
    _get_teams_for_usage_reports,
    UsageReportCounters,
    OrgReport,
    InstanceMetadata,
)
from posthog.constants import FlagRequestType


class UsageReportConfig(Config):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    dry_run: bool = False


def get_period(config: UsageReportConfig) -> tuple[datetime, datetime]:
    if config.end_date:
        period_end = datetime.fromisoformat(config.end_date)
    else:
        period_end = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if config.start_date:
        period_start = datetime.fromisoformat(config.start_date)
    else:
        period_start = period_end - timedelta(days=1)

    return period_start, period_end


def get_table_name(base_name: str, period_start: datetime) -> str:
    """Get the table name with date suffix."""
    date_suffix = period_start.strftime("%Y%m%d")
    return f"{base_name}_{date_suffix}"


def get_all_table_names(period_start: datetime) -> List[str]:
    """Get all table names for the given date."""
    base_tables = [
        "usage_event_counts",
        "usage_enhanced_persons_counts",
        "usage_events_with_groups_counts",
        "usage_recording_counts",
        "usage_mobile_recording_counts",
        "usage_feature_flag_counts",
        "usage_survey_response_counts",
        "usage_rows_synced_counts",
        "usage_query_app_bytes_read",
        "usage_query_api_bytes_read",
        "usage_query_app_rows_read",
        "usage_query_api_rows_read",
        "usage_query_app_duration_ms",
        "usage_query_api_duration_ms",
        "usage_hog_function_counts",
        "usage_hog_function_fetch_counts",
    ]
    return [get_table_name(base_name, period_start) for base_name in base_tables]


@asset
def create_usage_tables(context: AssetExecutionContext, config: UsageReportConfig):
    """Create temporary tables to store usage data."""
    period_start, _ = get_period(config)
    tables = get_all_table_names(period_start)
    
    for table in tables:
        sync_execute(f"""
            CREATE TABLE IF NOT EXISTS {table} ON CLUSTER '{{cluster}}'
            (
                team_id Int64,
                count Int64,
                created_at DateTime DEFAULT now()
            )
            ENGINE = ReplicatedMergeTree('/clickhouse/{{cluster}}/tables/{{database}}/{table}', '{{replica}}')
            ORDER BY team_id
        """)

    return MaterializeResult(
        metadata={
            "tables_created": MetadataValue.int(len(tables)),
            "period_start": MetadataValue.text(period_start.isoformat()),
        }
    )


@asset(deps=[create_usage_tables])
def event_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get billable event counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_billable_event_count_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_event_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def enhanced_persons_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get enhanced persons event counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_billable_enhanced_persons_event_count_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_enhanced_persons_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def events_with_groups_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get event counts with groups for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_event_count_with_groups_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_events_with_groups_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def all_event_metrics(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[str, Dict[int, int]]:
    """Get all event metrics for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_all_event_metrics_in_period(period_start, period_end)
    
    for metric_name, metric_results in results.items():
        table_name = get_table_name(f"usage_{metric_name}_counts", period_start)
        sync_execute(
            f"""
            INSERT INTO {table_name} (team_id, count)
            VALUES
            """,
            [(team_id, count) for team_id, count in metric_results.items()],
        )
    
    return results


@asset(deps=[create_usage_tables])
def recording_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get recording counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_recording_count_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_recording_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def mobile_recording_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get mobile recording counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_recording_count_in_period(period_start, period_end, snapshot_source="mobile")
    
    table_name = get_table_name("usage_mobile_recording_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def feature_flag_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get feature flag request counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_feature_flag_requests_count_in_period(period_start, period_end, FlagRequestType.DECIDE)
    
    table_name = get_table_name("usage_feature_flag_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def survey_response_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get survey response counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_survey_responses_count_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_survey_response_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def rows_synced_counts(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get rows synced counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_rows_synced_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_rows_synced_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def query_metrics(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[str, Dict[int, int]]:
    """Get query metrics for all teams."""
    period_start, period_end = get_period(config)
    
    metrics = {
        "read_bytes": "bytes_read",
        "read_rows": "rows_read",
        "query_duration_ms": "duration_ms",
    }
    
    results = {}
    for metric_type, table_suffix in metrics.items():
        app_results = get_teams_with_query_metric(
            period_start,
            period_end,
            access_method="app",
            metric=metric_type,
        )
        api_results = get_teams_with_query_metric(
            period_start,
            period_end,
            access_method="api",
            metric=metric_type,
        )
        
        # Store app results
        app_table = get_table_name(f"usage_query_app_{table_suffix}", period_start)
        sync_execute(
            f"""
            INSERT INTO {app_table} (team_id, count)
            VALUES
            """,
            [(team_id, count) for team_id, count in app_results],
        )
        
        # Store api results
        api_table = get_table_name(f"usage_query_api_{table_suffix}", period_start)
        sync_execute(
            f"""
            INSERT INTO {api_table} (team_id, count)
            VALUES
            """,
            [(team_id, count) for team_id, count in api_results],
        )
        
        results[f"app_{metric_type}"] = dict(app_results)
        results[f"api_{metric_type}"] = dict(api_results)
    
    return results


@asset(deps=[create_usage_tables])
def hog_function_calls(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get hog function call counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_hog_function_calls_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_hog_function_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset(deps=[create_usage_tables])
def hog_function_fetch_calls(context: AssetExecutionContext, config: UsageReportConfig) -> Dict[int, int]:
    """Get hog function fetch call counts for all teams."""
    period_start, period_end = get_period(config)
    
    results = get_teams_with_hog_function_fetch_calls_in_period(period_start, period_end)
    
    table_name = get_table_name("usage_hog_function_fetch_counts", period_start)
    sync_execute(
        f"""
        INSERT INTO {table_name} (team_id, count)
        VALUES
        """,
        [(team_id, count) for team_id, count in results],
    )
    
    return dict(results)


@asset
def instance_metadata(context: AssetExecutionContext, config: UsageReportConfig) -> InstanceMetadata:
    """Get instance metadata."""
    period_start, period_end = get_period(config)
    return get_instance_metadata((period_start, period_end))


@asset(
    deps=[
        event_counts,
        enhanced_persons_counts,
        events_with_groups_counts,
        all_event_metrics,
        recording_counts,
        mobile_recording_counts,
        feature_flag_counts,
        survey_response_counts,
        rows_synced_counts,
        query_metrics,
        hog_function_calls,
        hog_function_fetch_calls,
        instance_metadata,
    ]
)
def generate_usage_report(
    context: AssetExecutionContext,
    config: UsageReportConfig,
    event_counts: Dict[int, int],
    enhanced_persons_counts: Dict[int, int],
    events_with_groups_counts: Dict[int, int],
    all_event_metrics: Dict[str, Dict[int, int]],
    recording_counts: Dict[int, int],
    mobile_recording_counts: Dict[int, int],
    feature_flag_counts: Dict[int, int],
    survey_response_counts: Dict[int, int],
    rows_synced_counts: Dict[int, int],
    query_metrics: Dict[str, Dict[int, int]],
    hog_function_calls: Dict[int, int],
    hog_function_fetch_calls: Dict[int, int],
    instance_metadata: InstanceMetadata,
) -> None:
    """Generate and send usage report to billing service."""
    period_start, period_end = get_period(config)
    
    # Clean up temporary tables
    tables = get_all_table_names(period_start)
    for table in tables:
        sync_execute(f"TRUNCATE TABLE {table} ON CLUSTER '{{cluster}}'")
    
    teams = _get_teams_for_usage_reports()
    
    for team in teams:
        team_report = UsageReportCounters(
            event_count_in_period=event_counts.get(team.id, 0),
            enhanced_persons_event_count_in_period=enhanced_persons_counts.get(team.id, 0),
            event_count_with_groups_in_period=events_with_groups_counts.get(team.id, 0),
            recording_count_in_period=recording_counts.get(team.id, 0),
            mobile_recording_count_in_period=mobile_recording_counts.get(team.id, 0),
            billable_feature_flag_requests_count_in_period=feature_flag_counts.get(team.id, 0),
            survey_responses_count_in_period=survey_response_counts.get(team.id, 0),
            rows_synced_in_period=rows_synced_counts.get(team.id, 0),
            query_app_bytes_read=query_metrics["app_read_bytes"].get(team.id, 0),
            query_api_bytes_read=query_metrics["api_read_bytes"].get(team.id, 0),
            query_app_rows_read=query_metrics["app_read_rows"].get(team.id, 0),
            query_api_rows_read=query_metrics["api_read_rows"].get(team.id, 0),
            query_app_duration_ms=query_metrics["app_query_duration_ms"].get(team.id, 0),
            query_api_duration_ms=query_metrics["api_query_duration_ms"].get(team.id, 0),
            hog_function_calls_in_period=hog_function_calls.get(team.id, 0),
            hog_function_fetch_calls_in_period=hog_function_fetch_calls.get(team.id, 0),
        )
        
        if not config.dry_run:
            send_report_to_billing_service(str(team.organization_id), dataclasses.asdict(team_report))
    
    return MaterializeResult(
        metadata={
            "teams_processed": MetadataValue.int(len(teams)),
            "period_start": MetadataValue.text(period_start.isoformat()),
            "period_end": MetadataValue.text(period_end.isoformat()),
            "tables_cleaned": MetadataValue.int(len(tables)),
        }
    )
