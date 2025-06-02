import dagster
import dagster_slack

from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import S3Resource
from django.conf import settings

from dags.common import ClickhouseClusterResource, job_status_metrics_sensors
from dags import (
    backups,
    ch_examples,
    deletes,
    exchange_rate,
    export_query_logs_to_s3,
    materialized_columns,
    orm_examples,
    person_overrides,
    property_definitions,
    slack_alerts,
    web_preaggregated_internal,
)

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
    assets=[
        ch_examples.get_clickhouse_version,
        ch_examples.print_clickhouse_version,
        exchange_rate.daily_exchange_rates,
        exchange_rate.hourly_exchange_rates,
        exchange_rate.daily_exchange_rates_in_clickhouse,
        exchange_rate.hourly_exchange_rates_in_clickhouse,
        orm_examples.pending_deletions,
        orm_examples.process_pending_deletions,
        web_preaggregated_internal.web_analytics_preaggregated_tables,
        web_preaggregated_internal.web_stats_daily,
        web_preaggregated_internal.web_bounces_daily,
    ],
    jobs=[
        deletes.deletes_job,
        exchange_rate.daily_exchange_rates_job,
        exchange_rate.hourly_exchange_rates_job,
        export_query_logs_to_s3.export_query_logs_to_s3,
        materialized_columns.materialize_column,
        person_overrides.cleanup_orphaned_person_overrides_snapshot,
        person_overrides.squash_person_overrides,
        property_definitions.property_definitions_ingestion_job,
        backups.sharded_backup,
        backups.non_sharded_backup,
        web_preaggregated_internal.recreate_web_pre_aggregated_data_job,
    ],
    schedules=[
        exchange_rate.daily_exchange_rates_schedule,
        exchange_rate.hourly_exchange_rates_schedule,
        export_query_logs_to_s3.query_logs_export_schedule,
        person_overrides.squash_schedule,
        property_definitions.property_definitions_hourly_schedule,
        backups.full_sharded_backup_schedule,
        backups.incremental_sharded_backup_schedule,
        backups.full_non_sharded_backup_schedule,
        backups.incremental_non_sharded_backup_schedule,
        web_preaggregated_internal.recreate_web_analytics_preaggregated_internal_data_daily,
    ],
    sensors=[
        deletes.run_deletes_after_squash,
        slack_alerts.notify_slack_on_failure,
        *job_status_metrics_sensors,
    ],
    resources=resources,
)

if settings.DEBUG:
    from . import testing

    defs.jobs.append(testing.error)
