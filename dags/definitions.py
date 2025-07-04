# TODO: REMOVE THIS FILE ONCE WE MOVE EVERYTHING TO DAGSTER CLOUD

import dagster
import dagster_slack

from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import S3Resource
from django.conf import settings

from dags.common import ClickhouseClusterResource

# Define resources for different environments
resources_by_env = {
    "prod": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": s3_pickle_io_manager.configured(
            {"s3_bucket": settings.DAGSTER_S3_BUCKET, "s3_prefix": "dag-storage"}
        ),
        "s3": S3Resource(),
        # Using EnvVar instead of the Django setting to ensure that the token is not leaked anywhere in the Dagster UI
        "slack": dagster_slack.SlackResource(token=dagster.EnvVar("SLACK_TOKEN")),
    },
    "local": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": dagster.fs_io_manager,
        "slack": dagster.ResourceDefinition.none_resource(description="Dummy Slack resource for local development"),
        "s3": S3Resource(),
    },
}


# Get resources for current environment, fallback to local if env not found
env = "local" if settings.DEBUG else "prod"
resources = resources_by_env.get(env, resources_by_env["local"])

defs = dagster.Definitions(
    # assets=[
    #     ch_examples.get_clickhouse_version,
    #     ch_examples.print_clickhouse_version,
    #     exchange_rate.daily_exchange_rates,
    #     exchange_rate.hourly_exchange_rates,
    #     exchange_rate.daily_exchange_rates_in_clickhouse,
    #     exchange_rate.hourly_exchange_rates_in_clickhouse,
    #     orm_examples.pending_deletions,
    #     orm_examples.process_pending_deletions,
    #     symbol_set_cleanup.symbol_sets_to_delete,
    #     symbol_set_cleanup.symbol_set_cleanup_results,
    #     web_preaggregated_ddl.web_analytics_preaggregated_tables,
    #     web_preaggregated_ddl.web_analytics_preaggregated_hourly_tables,
    #     web_preaggregated_ddl.web_analytics_combined_views,
    #     web_preaggregated_daily.web_stats_daily,
    #     web_preaggregated_daily.web_bounces_daily,
    #     web_preaggregated_daily.web_stats_daily_export,
    #     web_preaggregated_daily.web_bounces_daily_export,
    #     web_preaggregated_hourly.web_stats_hourly,
    #     web_preaggregated_hourly.web_bounces_hourly,
    # ],
    # asset_checks=[
    #     web_preaggregated_asset_checks.web_analytics_accuracy_check,
    #     web_preaggregated_asset_checks.stats_daily_has_data,
    #     web_preaggregated_asset_checks.stats_hourly_has_data,
    #     web_preaggregated_asset_checks.bounces_daily_has_data,
    #     web_preaggregated_asset_checks.bounces_hourly_has_data,
    #     web_preaggregated_asset_checks.stats_export_chdb_queryable,
    #     web_preaggregated_asset_checks.bounces_export_chdb_queryable,
    #     web_preaggregated_ddl.daily_stats_table_exist,
    #     web_preaggregated_ddl.daily_bounces_table_exist,
    #     web_preaggregated_ddl.hourly_stats_table_exist,
    #     web_preaggregated_ddl.hourly_bounces_table_exist,
    #     web_preaggregated_ddl.combined_stats_view_exist,
    #     web_preaggregated_ddl.combined_bounces_view_exist,
    # ],
    # jobs=[
    #     deletes.deletes_job,
    #     exchange_rate.daily_exchange_rates_job,
    #     exchange_rate.hourly_exchange_rates_job,
    #     export_query_logs_to_s3.export_query_logs_to_s3,
    #     materialized_columns.materialize_column,
    #     person_overrides.cleanup_orphaned_person_overrides_snapshot,
    #     person_overrides.squash_person_overrides,
    #     property_definitions.property_definitions_ingestion_job,
    #     symbol_set_cleanup.symbol_set_cleanup_job,
    #     backups.sharded_backup,
    #     backups.non_sharded_backup,
    #     web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_job,
    #     web_preaggregated_daily.web_pre_aggregate_daily_job,
    #     web_preaggregated_asset_checks.web_analytics_data_quality_job,
    #     web_preaggregated_asset_checks.simple_data_checks_job,
    #     oauth.oauth_clear_expired_oauth_tokens_job,
    # ],
    # schedules=[
    #     exchange_rate.daily_exchange_rates_schedule,
    #     exchange_rate.hourly_exchange_rates_schedule,
    #     export_query_logs_to_s3.query_logs_export_schedule,
    #     person_overrides.squash_schedule,
    #     property_definitions.property_definitions_hourly_schedule,
    #     backups.full_sharded_backup_schedule,
    #     backups.incremental_sharded_backup_schedule,
    #     backups.full_non_sharded_backup_schedule,
    #     backups.incremental_non_sharded_backup_schedule,
    #     symbol_set_cleanup.daily_symbol_set_cleanup_schedule,
    #     web_preaggregated_daily.web_pre_aggregate_daily_schedule,
    #     web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_schedule,
    #     web_preaggregated_asset_checks.web_analytics_weekly_data_quality_schedule,
    #     oauth.oauth_clear_expired_oauth_tokens_schedule,
    # ],
    # sensors=[
    #     deletes.run_deletes_after_squash,
    #     slack_alerts.notify_slack_on_failure,
    #     *job_status_metrics_sensors,
    # ],
    # resources=resources,
)
