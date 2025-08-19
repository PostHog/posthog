import asyncio
import os
from collections.abc import Generator
from io import BytesIO
from typing import TYPE_CHECKING, Annotated, Any, TypeVar
from unittest.mock import patch

import aioboto3
import aioboto3.s3
import backoff
import pytest
from asgiref.sync import async_to_sync, sync_to_async
from dagster_pipes import PipesContext, open_dagster_pipes
from fastavro import reader
from pydantic import BaseModel, ConfigDict, SkipValidation
from pydantic_avro import AvroBase

# We want the PostHog setup_evals fixture here
from ee.hogai.eval.conftest import setup_evals  # noqa: F401
from ee.hogai.eval.schema import (
    ActorsPropertyTaxonomySnapshot,
    DatasetInput,
    DataWarehouseTableSnapshot,
    EvalsDockerImageConfig,
    GroupTypeMappingSnapshot,
    ProjectSnapshot,
    PropertyDefinitionSnapshot,
    PropertyTaxonomySnapshot,
    TeamSnapshot,
    TeamTaxonomyItemSnapshot,
)
from posthog.models import (
    GroupTypeMapping,
    Organization,
    Project,
    PropertyDefinition,
    Team,
    User,
)
from posthog.warehouse.models.table import DataWarehouseTable

from .query_patches import (
    ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE,
    EVENT_TAXONOMY_QUERY_DATA_SOURCE,
    TEAM_TAXONOMY_QUERY_DATA_SOURCE,
    PatchedActorsPropertyTaxonomyQueryRunner,
    PatchedEventTaxonomyQueryRunner,
    PatchedTeamTaxonomyQueryRunner,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


T = TypeVar("T", bound=AvroBase)


class SnapshotLoader:
    def __init__(self, context: PipesContext):
        self.context = context
        self.config = EvalsDockerImageConfig.model_validate(context.extras)
        self.patches: list[Any] = []

    async def load_snapshots(self) -> tuple[Organization, User, list[DatasetInput]]:
        self.organization = await Organization.objects.acreate(name="PostHog")
        self.user = await sync_to_async(User.objects.create_and_join)(self.organization, "test@posthog.com", "12345678")

        # clickhouse_query_snapshots: dict[int, dict[str,]] = {}
        for snapshot in self.config.project_snapshots:
            self.context.log.info(f"Loading Postgres snapshot for team {snapshot.project}...")

            project = await Project.objects.acreate(
                id=await sync_to_async(Team.objects.increment_id_sequence)(), organization=self.organization
            )

            (
                project_snapshot_bytes,
                property_definitions_snapshot_bytes,
                group_type_mappings_snapshot_bytes,
                data_warehouse_tables_snapshot_bytes,
                event_taxonomy_snapshot_bytes,
                properties_taxonomy_snapshot_bytes,
                actors_property_taxonomy_snapshot_bytes,
            ) = await self._get_all_snapshots(snapshot)

            team = await self._load_project_snapshot(project, snapshot.project, project_snapshot_bytes)
            await asyncio.gather(
                self._load_property_definitions(team, property_definitions_snapshot_bytes),
                self._load_group_type_mappings(team, group_type_mappings_snapshot_bytes),
                self._load_data_warehouse_tables(team, data_warehouse_tables_snapshot_bytes),
            )
            self._load_event_taxonomy(team, event_taxonomy_snapshot_bytes)
            self._load_properties_taxonomy(team, properties_taxonomy_snapshot_bytes)
            self._load_actors_property_taxonomy(team, actors_property_taxonomy_snapshot_bytes)

        self._patch_query_runners()

        return self.organization, self.user, self.config.dataset

    def cleanup(self):
        for mock in self.patches:
            mock.stop()

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def _get_all_snapshots(self, snapshot: ProjectSnapshot):
        async with aioboto3.Session().client(
            "s3",
            endpoint_url=self.config.aws_endpoint_url,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        ) as client:
            loaded_snapshots = await asyncio.gather(
                self._get_snapshot_from_s3(client, snapshot.postgres.project),
                self._get_snapshot_from_s3(client, snapshot.postgres.property_definitions),
                self._get_snapshot_from_s3(client, snapshot.postgres.group_type_mappings),
                self._get_snapshot_from_s3(client, snapshot.postgres.data_warehouse_tables),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.event_taxonomy),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.properties_taxonomy),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.actors_property_taxonomy),
            )
            return loaded_snapshots

    async def _get_snapshot_from_s3(self, client: "S3Client", file_key: str):
        response = await client.get_object(Bucket=self.config.aws_bucket_name, Key=file_key)
        content = await response["Body"].read()
        return BytesIO(content)

    def _parse_snapshot_to_schema(self, schema: type[T], buffer: BytesIO) -> Generator[T, None, None]:
        for record in reader(buffer):
            yield schema.model_validate(record)

    async def _load_project_snapshot(self, project: Project, team_id: int, buffer: BytesIO) -> Team:
        project_snapshot = next(self._parse_snapshot_to_schema(TeamSnapshot, buffer))
        team = next(TeamSnapshot.deserialize_for_project(team_id, [project_snapshot]))
        team.project = project
        team.organization = self.organization
        team.api_token = f"team_{team_id}"
        await team.asave()
        return team

    async def _load_property_definitions(self, team: Team, buffer: BytesIO):
        snapshot = list(self._parse_snapshot_to_schema(PropertyDefinitionSnapshot, buffer))
        property_definitions = PropertyDefinitionSnapshot.deserialize_for_project(team.id, snapshot)
        return await PropertyDefinition.objects.abulk_create(property_definitions, batch_size=500)

    async def _load_group_type_mappings(self, team: Team, buffer: BytesIO):
        snapshot = list(self._parse_snapshot_to_schema(GroupTypeMappingSnapshot, buffer))
        group_type_mappings = GroupTypeMappingSnapshot.deserialize_for_project(team.id, snapshot, team_id=team.id)
        return await GroupTypeMapping.objects.abulk_create(group_type_mappings, batch_size=500)

    async def _load_data_warehouse_tables(self, team: Team, buffer: BytesIO):
        snapshot = list(self._parse_snapshot_to_schema(DataWarehouseTableSnapshot, buffer))
        data_warehouse_tables = DataWarehouseTableSnapshot.deserialize_for_project(team.id, snapshot)
        return await DataWarehouseTable.objects.abulk_create(data_warehouse_tables, batch_size=500)

    def _load_event_taxonomy(self, team: Team, buffer: BytesIO):
        snapshot = next(self._parse_snapshot_to_schema(TeamTaxonomyItemSnapshot, buffer))
        TEAM_TAXONOMY_QUERY_DATA_SOURCE[team.id] = snapshot.results

    def _load_properties_taxonomy(self, team: Team, buffer: BytesIO):
        for item in self._parse_snapshot_to_schema(PropertyTaxonomySnapshot, buffer):
            EVENT_TAXONOMY_QUERY_DATA_SOURCE[team.id][item.event] = item.results

    def _load_actors_property_taxonomy(self, team: Team, buffer: BytesIO):
        for item in self._parse_snapshot_to_schema(ActorsPropertyTaxonomySnapshot, buffer):
            key = item.group_type_index if isinstance(item.group_type_index, int) else "person"
            ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[team.id][key] = item.results

    def _patch_query_runners(self):
        self.patches = [
            patch(
                "posthog.hogql_queries.ai.team_taxonomy_query_runner.TeamTaxonomyQueryRunner",
                new=PatchedTeamTaxonomyQueryRunner,
            ),
            patch(
                "posthog.hogql_queries.ai.event_taxonomy_query_runner.EventTaxonomyQueryRunner",
                new=PatchedEventTaxonomyQueryRunner,
            ),
            patch(
                "posthog.hogql_queries.ai.actors_property_taxonomy_query_runner.ActorsPropertyTaxonomyQueryRunner",
                new=PatchedActorsPropertyTaxonomyQueryRunner,
            ),
        ]
        for mock in self.patches:
            mock.start()


@pytest.fixture(scope="package")
def dagster_context() -> Generator[PipesContext, None, None]:
    with open_dagster_pipes() as context:
        yield context


class EvaluationContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    organization: Annotated[Organization, SkipValidation]
    user: Annotated[User, SkipValidation]
    experiment_name: str
    dataset: list[DatasetInput]


@pytest.fixture(scope="package", autouse=True)
def eval_ctx(setup_evals, dagster_context: PipesContext, django_db_blocker) -> Generator[EvaluationContext, None, None]:  # noqa: F811
    """
    Script that restores dumped Django models and patches AI query runners.
    Creates teams with team_id=project_id for the same single user and organization,
    keeping the original project_ids for teams.
    """
    with django_db_blocker.unblock():
        dagster_context.log.info(f"Loading Postgres and ClickHouse snapshots...")

        loader = SnapshotLoader(dagster_context)
        org, user, dataset = async_to_sync(loader.load_snapshots)()

        dagster_context.log.info(f"Running tests...")
        yield EvaluationContext(
            organization=org,
            user=user,
            experiment_name=loader.config.experiment_name,
            dataset=dataset,
        )

        dagster_context.log.info(f"Cleaning up...")
        loader.cleanup()

        dagster_context.log.info(f"Reporting results...")
        with open("eval_results.jsonl") as f:
            lines = f.readlines()
            dagster_context.report_asset_materialization(
                asset_key="evaluation_report",
                metadata={
                    "output": "\n".join(lines),
                },
            )
