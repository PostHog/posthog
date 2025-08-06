import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from io import BytesIO
from typing import TYPE_CHECKING, TypeVar

import aioboto3
import aioboto3.s3
import backoff
import pytest
from dagster_pipes import open_dagster_pipes
from fastavro import parse_schema, reader
from pydantic_avro import AvroBase

from ee.hogai.eval.schema import (
    EvalsDockerImageConfig,
    PropertyDefinitionSchema,
    Snapshot,
    TeamSchema,
)
from posthog.models import Organization, Project, PropertyDefinition, Team, User

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


T = TypeVar("T", bound=AvroBase)


class SnapshotLoader:
    def __init__(self, config: EvalsDockerImageConfig):
        self.config = config
        self.organization = Organization.objects.create(name="PostHog")
        self.user = User.objects.create_and_join(self.organization, "test@posthog.com", "12345678")

    async def load_snapshots(self) -> tuple[Organization, User]:
        for snapshot in self.config.project_snapshots:
            project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=self.organization)

            (
                project_snapshot_bytes,
                property_definitions_snapshot_bytes,
                data_warehouse_tables_snapshot_bytes,
                event_taxonomy_snapshot_bytes,
                properties_taxonomy_snapshot_bytes,
            ) = await self._get_all_snapshots(snapshot)

            team = await self._load_project_snapshot(project, snapshot.project, project_snapshot_bytes)
            await self._load_property_definitions(team, property_definitions_snapshot_bytes)
        return self.organization, self.user

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def _get_all_snapshots(self, snapshot: Snapshot):
        async with aioboto3.Session().client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        ) as client:
            loaded_snapshots = await asyncio.gather(
                self._get_snapshot_from_s3(client, snapshot.postgres.project),
                self._get_snapshot_from_s3(client, snapshot.postgres.property_definitions),
                self._get_snapshot_from_s3(client, snapshot.postgres.data_warehouse_tables),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.event_taxonomy),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.properties_taxonomy),
            )
            return loaded_snapshots

    async def _get_snapshot_from_s3(self, client: S3Client, file_key: str):
        response = await client.get_object(Bucket=self.config.bucket_name, Key=file_key)
        content = await response["Body"].read()
        return BytesIO(content)

    def _parse_snapshot_to_schema(self, schema: type[T], buffer: BytesIO) -> Generator[T, None, None]:
        avro_schema = parse_schema(schema.avro_schema)
        for record in reader(buffer, avro_schema):
            yield schema.model_validate(record)

    async def _load_project_snapshot(self, project: Project, team_id: int, buffer: BytesIO) -> Team:
        project_snapshot = next(self._parse_snapshot_to_schema(TeamSchema, buffer))
        team = next(TeamSchema.deserialize_for_project(team_id, [project_snapshot]))
        team.project = project
        team.organization = self.organization
        team.api_token = f"team_{team_id}"
        await team.asave()
        return team

    async def _load_property_definitions(self, team: Team, buffer: BytesIO):
        snapshot = list(self._parse_snapshot_to_schema(PropertyDefinitionSchema, buffer))
        property_definitions = PropertyDefinitionSchema.deserialize_for_project(team.id, snapshot)
        return await PropertyDefinition.objects.abulk_create(property_definitions, batch_size=500)


@pytest.fixture(scope="package")
async def restore_postgres_snapshot(
    django_db_setup, django_db_blocker
) -> AsyncGenerator[tuple[Organization, User], None]:
    """
    Script that restores dumped Django models.
    Creates teams with team_id=project_id for the same single user and organization,
    keeping the original project_ids for teams.
    """
    with django_db_blocker.unblock(), open_dagster_pipes() as context:
        config = EvalsDockerImageConfig.model_validate(context.extras)
        loader = SnapshotLoader(config)
        org, user = await loader.load_snapshots()
        yield org, user
