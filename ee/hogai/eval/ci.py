import os
from io import BytesIO
from typing import TYPE_CHECKING

import boto3
import boto3.s3
from dagster_pipes import open_dagster_pipes
from pydantic import BaseModel

from dags.max_ai.schema import (
    Snapshot,
    TeamSchema,
)
from posthog.models import Organization, Project, Team, User

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client


class EvalsDockerImageConfig(BaseModel):
    class Config:
        extra = "allow"

    bucket_name: str
    endpoint_url: str
    project_snapshots: list[Snapshot]


def get_snapshot_from_s3(client: S3Client, config: EvalsDockerImageConfig):
    s3 = client.client("s3")
    response = s3.get_object(Bucket=config.bucket_name, Key=config.file_key)
    return BytesIO(response["Body"].read())


def restore_postgres_snapshot():
    """
    Script that restores dumped Django models.
    Creates teams with team_id=project_id for the same single user and organization,
    keeping the original project_ids for teams.
    """
    with open_dagster_pipes() as context:
        config = EvalsDockerImageConfig.model_validate(context.extras)

        organization = Organization.objects.create(name="PostHog")
        user = User.objects.create_and_join(organization, "test@posthog.com", "12345678")

        s3_client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        )

        for snapshot in config.project_snapshots:
            project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=organization)

            s3_client.get_object(Bucket=config.bucket_name, Key=config.file_key)
            team = TeamSchema.deserialize_for_project(snapshot.project, snapshot.postgres.project)
            team.project = project
            team.organization = organization
            team.api_token = f"team_{snapshot.project}"
            team.save()

    return organization, user
