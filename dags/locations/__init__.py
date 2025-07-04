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
