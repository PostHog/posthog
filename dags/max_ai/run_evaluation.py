import base64
from typing import Any, cast
from uuid import UUID

from django.conf import settings

import boto3
import dagster
from dagster._core.definitions.metadata import RawMetadataMapping
from dagster_docker import PipesDockerClient
from dagster_slack import SlackResource
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from products.llm_analytics.backend.models import Dataset, DatasetItem

from dags.common import JobOwners
from dags.max_ai.snapshot_team_data import (
    ClickhouseTeamDataSnapshot,
    PostgresTeamDataSnapshot,
    snapshot_clickhouse_team_data,
    snapshot_postgres_team_data,
)
from dags.max_ai.utils import EvaluationResults, format_results
from ee.hogai.eval.schema import DatasetInput, EvalsDockerImageConfig, TeamEvaluationSnapshot


def get_object_storage_endpoint() -> str:
    """
    Get the object storage endpoint.
    Debug mode uses the local object storage, so we need to set a DNS endpoint (like orb.dev).
    Production mode uses the AWS S3.
    """
    if settings.DEBUG:
        val = dagster.EnvVar("EVALS_DIND_OBJECT_STORAGE_ENDPOINT").get_value("http://objectstorage.posthog.orb.local")
        if not val:
            raise ValueError("EVALS_DIND_OBJECT_STORAGE_ENDPOINT is not set")
        return val
    return settings.OBJECT_STORAGE_ENDPOINT


class PrepareDatasetConfig(dagster.Config):
    dataset_id: str
    """Dataset ID to run the evaluation for."""


class PreparedDataset(BaseModel):
    dataset_id: UUID
    dataset_name: str
    dataset_inputs: list[DatasetInput]


def _get_team_id() -> int:
    return 2 if not settings.DEBUG else 1


@dagster.op(
    description="Pulls the dataset and dataset items and validates inputs, outputs, metadata, and team_id presence in metadata."
)
def prepare_dataset(context: dagster.OpExecutionContext, config: PrepareDatasetConfig) -> PreparedDataset:
    dataset = Dataset.objects.exclude(deleted=True).get(id=config.dataset_id, team_id=_get_team_id())
    dataset_items = DatasetItem.objects.exclude(deleted=True).filter(dataset=dataset).iterator(500)

    dataset_inputs: list[DatasetInput] = []
    for dataset_item in dataset_items:
        try:
            metadata = dataset_item.metadata or {}
            dataset_inputs.append(
                DatasetInput(
                    input=dataset_item.input,
                    expected=dataset_item.output,
                    metadata=metadata,
                    team_id=metadata.get("team_id"),
                )
            )
        except ValidationError:
            context.log.exception(f"Validation error for dataset item {dataset_item.id}")
            raise

    return PreparedDataset(dataset_id=dataset.id, dataset_name=dataset.name, dataset_inputs=dataset_inputs)


@dagster.op(out=dagster.DynamicOut(int))
def prepare_evaluation(prepared_dataset: PreparedDataset):
    seen_teams = set()
    for dataset_input in prepared_dataset.dataset_inputs:
        if dataset_input.team_id in seen_teams:
            continue
        seen_teams.add(dataset_input.team_id)
        yield dagster.DynamicOutput(dataset_input.team_id, mapping_key=str(dataset_input.team_id))


class EvaluationConfig(dagster.Config):
    image_name: str = Field(description="Name of the Docker image to run.")
    image_tag: str = Field(description="Tag of the Docker image to run.")
    evaluation_module: str = Field(description="Python module containing the evaluation runner.")

    @property
    def image(self) -> str:
        # We use the local Docker image in debug mode
        if settings.DEBUG:
            return f"{self.image_name}:{self.image_tag}"
        return f"{dagster.EnvVar('AWS_EKS_REGISTRY_URL').get_value()}/{self.image_name}:{self.image_tag}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2))
def get_registry_credentials():
    # We use the local Docker image in debug mode
    if settings.DEBUG:
        return None

    client = boto3.client("ecr")
    # https://boto3.amazonaws.com/v1/documentation/api/1.29.2/reference/services/ecr/client/get_authorization_token.html
    token = client.get_authorization_token()["authorizationData"][0]["authorizationToken"]
    username, password = base64.b64decode(token).decode("utf-8").split(":")

    return {
        "url": dagster.EnvVar("AWS_EKS_REGISTRY_URL").get_value(),
        "username": username,
        "password": password,
    }


def unpack_evaluation_results(metadata: RawMetadataMapping | None) -> EvaluationResults | None:
    if not metadata:
        return None
    try:
        meta = metadata["evaluation_results"]
        if isinstance(meta, dagster.JsonMetadataValue):
            return cast(list[dict[Any, Any]], meta.value)
        return None
    except KeyError:
        return None


def get_last_dataset_materialization_metadata(
    context: dagster.OpExecutionContext, asset_key: dagster.AssetKey
) -> EvaluationResults | None:
    last_materialization_event = context.instance.get_latest_materialization_event(asset_key)
    if not last_materialization_event or not last_materialization_event.asset_materialization:
        return None
    return unpack_evaluation_results(last_materialization_event.asset_materialization.metadata)


@dagster.op
def spawn_evaluation_container(
    context: dagster.OpExecutionContext,
    config: EvaluationConfig,
    docker_pipes_client: PipesDockerClient,
    slack: SlackResource,
    prepared_dataset: PreparedDataset,
    team_ids: list[int],
    postgres_snapshots: list[PostgresTeamDataSnapshot],
    clickhouse_snapshots: list[ClickhouseTeamDataSnapshot],
):
    # Validate the evaluation module
    if not config.evaluation_module.endswith(".py"):
        raise ValueError("Evaluation module must be a Python file")
    if not config.evaluation_module.startswith("ee/hogai/eval/"):
        raise ValueError(f"Evaluation module {config.evaluation_module} must start with 'ee/hogai/eval/'")

    asset_key = dagster.AssetKey(["evaluation_dataset", str(prepared_dataset.dataset_id)])
    evaluation_config = EvalsDockerImageConfig(
        aws_endpoint_url=get_object_storage_endpoint(),
        aws_bucket_name=settings.OBJECT_STORAGE_BUCKET,
        team_snapshots=[
            TeamEvaluationSnapshot(team_id=team_id, postgres=postgres, clickhouse=clickhouse).model_dump()
            for team_id, postgres, clickhouse in zip(team_ids, postgres_snapshots, clickhouse_snapshots)
        ],
        experiment_id=context.run_id,
        experiment_name=f"dataset-{prepared_dataset.dataset_id}",
        dataset_id=str(prepared_dataset.dataset_id),
        dataset_name=prepared_dataset.dataset_name,
        dataset_inputs=prepared_dataset.dataset_inputs,
    )

    context.log.info(f"Running evaluation for the image: {config.image}")

    env: dict[str, str] = {
        "EVAL_SCRIPT": f"pytest {config.evaluation_module} -s -vv",
        "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,  # type: ignore
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,  # type: ignore
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
        "INKEEP_API_KEY": settings.INKEEP_API_KEY,
        "AZURE_INFERENCE_ENDPOINT": settings.AZURE_INFERENCE_ENDPOINT,
        "AZURE_INFERENCE_CREDENTIAL": settings.AZURE_INFERENCE_CREDENTIAL,
    }
    if settings.OPENAI_BASE_URL:
        env["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL

    asset_result = docker_pipes_client.run(
        context=context,
        image=config.image,
        container_kwargs={
            "privileged": True,
            "auto_remove": True,
        },
        env=env,
        extras=evaluation_config.model_dump(exclude_unset=True),
        registry=get_registry_credentials(),
    ).get_materialize_result()

    previous_results = get_last_dataset_materialization_metadata(context, asset_key)
    new_results = unpack_evaluation_results(asset_result.metadata)

    if not new_results:
        context.log.error("No new evaluation results returned")
        raise ValueError("No new evaluation results found")

    blocks, formatted_markdown = format_results(
        prepared_dataset.dataset_id, prepared_dataset.dataset_name, context.run_id, new_results, previous_results
    )
    try:
        slack.get_client().chat_postMessage(channel="#evals-max-ai", blocks=blocks)
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")

    context.log_event(
        dagster.AssetMaterialization(
            asset_key=asset_key,
            metadata={
                "evaluation_results": dagster.JsonMetadataValue(new_results),
                "report": dagster.MarkdownMetadataValue(formatted_markdown),
            },
            tags={
                "owner": JobOwners.TEAM_MAX_AI.value,
            },
        )
    )


@dagster.job(
    description="Runs an AI evaluation",
    tags={
        "owner": JobOwners.TEAM_MAX_AI.value,
        "dagster/max_runtime": 60 * 60,  # 1 hour
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 4}),
    config=dagster.RunConfig(
        ops={
            "prepare_dataset": PrepareDatasetConfig(dataset_id=""),
            "spawn_evaluation_container": EvaluationConfig(
                evaluation_module="ee/hogai/eval/offline/",
                image_name="posthog-ai-evals",
                image_tag="master",
            ),
        }
    ),
)
def run_evaluation():
    prepared_dataset = prepare_dataset()
    team_ids = prepare_evaluation(prepared_dataset)
    postgres_snapshots = team_ids.map(snapshot_postgres_team_data)
    clickhouse_snapshots = team_ids.map(snapshot_clickhouse_team_data)
    spawn_evaluation_container(
        prepared_dataset,
        team_ids.collect(),
        postgres_snapshots.collect(),
        clickhouse_snapshots.collect(),
    )
