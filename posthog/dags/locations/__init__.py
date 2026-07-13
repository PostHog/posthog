from django.conf import settings

import dagster
import dagster_slack
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import S3Resource

from posthog.dags.common.loggers import structlog_console_logger
from posthog.dags.common.resources import (
    ClayWebhookResource,
    ClickhouseClusterResource,
    PostgresResource,
    PostgresURLResource,
    PostHogAnalyticsResource,
    RedisResource,
    kafka_producer_resource,
)
from posthog.schema_build import build_all_schema_models

# Default loggers for every code location's jobs. Overrides Dagster's
# colored_console_logger so `context.log` emits structlog JSON to stdout (like
# Django) and reaches the PostHog Logs product. Shared as a single instance —
# Dagster errors if the same logger key maps to different objects across
# merged definitions.
loggers = {"console": structlog_console_logger}

# Define resources for different environments
resources_by_env = {
    "prod": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": s3_pickle_io_manager.configured(
            {"s3_bucket": settings.DAGSTER_S3_BUCKET, "s3_prefix": "dag-storage"}
        ),
        "redis_client": RedisResource(),
        "s3": S3Resource(),
        # Using EnvVar instead of the Django setting to ensure that the token is not leaked anywhere in the Dagster UI
        "slack": dagster_slack.SlackResource(token=dagster.EnvVar("SLACK_TOKEN")),
        # Postgres resource (universal for all dags)
        "database": PostgresResource(
            host=dagster.EnvVar("POSTGRES_HOST"),
            port=dagster.EnvVar("POSTGRES_PORT"),
            database=dagster.EnvVar("POSTGRES_DATABASE"),
            user=dagster.EnvVar("POSTGRES_USER"),
            password=dagster.EnvVar("POSTGRES_PASSWORD"),
        ),
        "posthoganalytics": dagster.ResourceDefinition.none_resource(
            description="Dummy PostHogAnalytics resource since posthoganalytics is configured properly in production."
        ),
        # Persons DB resource (parses connection URL)
        "persons_database": PostgresURLResource(
            connection_url=dagster.EnvVar("PERSONS_DB_WRITER_URL"),
        ),
        # Kafka producer (auto-configured from Django settings)
        "kafka_producer": kafka_producer_resource,
        # Clay webhook for job switchers pipeline
        "clay_webhook_job_switchers": ClayWebhookResource(
            webhook_url=dagster.EnvVar("CLAY_JOB_SWITCHERS_WEBHOOK_URL"),
            api_key=dagster.EnvVar("CLAY_JOB_SWITCHERS_API_KEY"),
        ),
        # Clay webhook for product-led outbound pipeline
        "clay_webhook_plo": ClayWebhookResource(
            webhook_url=dagster.EnvVar("CLAY_PRODUCT_LED_OUTBOUND_WEBHOOK_URL"),
            api_key=dagster.EnvVar("CLAY_PRODUCT_LED_OUTBOUND_API_KEY"),
        ),
    },
    "local": {
        "cluster": ClickhouseClusterResource.configure_at_launch(),
        "io_manager": dagster.fs_io_manager,
        "redis_client": RedisResource(),
        "s3": S3Resource(
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        ),
        "slack": dagster.ResourceDefinition.none_resource(description="Dummy Slack resource for local development"),
        # Postgres resource (universal for all dags) - use Django settings or env vars for local dev
        "database": PostgresResource(
            host=dagster.EnvVar("POSTGRES_HOST"),
            port=dagster.EnvVar("POSTGRES_PORT"),
            database=dagster.EnvVar("POSTGRES_DATABASE"),
            user=dagster.EnvVar("POSTGRES_USER"),
            password=dagster.EnvVar("POSTGRES_PASSWORD"),
        ),
        "posthoganalytics": PostHogAnalyticsResource(personal_api_key=dagster.EnvVar("PERSONAL_API_KEY")),
        # Persons DB resource (parses connection URL)
        "persons_database": PostgresURLResource(
            connection_url=dagster.EnvVar("PERSONS_DB_WRITER_URL"),
        ),
        # Kafka producer (auto-configured from Django settings)
        "kafka_producer": kafka_producer_resource,
        # Clay webhook for job switchers pipeline
        "clay_webhook_job_switchers": ClayWebhookResource(
            webhook_url=dagster.EnvVar("CLAY_JOB_SWITCHERS_WEBHOOK_URL"),
            api_key=dagster.EnvVar("CLAY_JOB_SWITCHERS_API_KEY"),
        ),
        # Clay webhook for product-led outbound pipeline
        "clay_webhook_plo": ClayWebhookResource(
            webhook_url=dagster.EnvVar("CLAY_PRODUCT_LED_OUTBOUND_WEBHOOK_URL"),
            api_key=dagster.EnvVar("CLAY_PRODUCT_LED_OUTBOUND_API_KEY"),
        ),
    },
}


# Get resources for current environment, fallback to local if env not found
env = "local" if settings.DEBUG else "prod"
resources = resources_by_env.get(env, resources_by_env["local"])


# See build_all_schema_models's docstring for why this build is eager. Every dagster
# code location imports this package (for `loggers`/`resources` above — an invisible but
# load-bearing coupling: a refactor that stops importing them here would silently drop
# dagster back to the lazy path), and both the definition server (dagit/code server) and
# per-run workers re-import the location module — so building here covers every process
# that loads this code location. Schema-model subclasses defined in later-imported
# location submodules still defer and use the guarded lazy path at first use; this only
# covers what's reachable from posthog.schema at this point in the import.
#
# Building here is paid per spawned subprocess, not shared copy-on-write: dagster's
# multiprocess and k8s job executors re-import this module per step worker, so each
# step pays the build cost even for ops that never touch schema models. This matches
# the pre-defer eager baseline and is batch-tolerant, so it's an accepted trade-off.
build_all_schema_models()
