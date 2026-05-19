from django.conf import settings

import dagster
import dagster_slack
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import S3Resource

from posthog.dags.common.resources import (
    ClayWebhookResource,
    ClickhouseClusterResource,
    PostgresResource,
    PostgresURLResource,
    PostHogAnalyticsResource,
    RedisResource,
    kafka_producer_resource,
)

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
