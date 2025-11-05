from django.conf import settings

import dagster
import dagster_slack
from dagster_aws.s3.io_manager import s3_pickle_io_manager
from dagster_aws.s3.resources import S3Resource

from dags.common import ClickhouseClusterResource, RedisResource

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
    },
}


# Get resources for current environment, fallback to local if env not found
env = "local" if settings.DEBUG else "prod"
resources = resources_by_env.get(env, resources_by_env["local"])
