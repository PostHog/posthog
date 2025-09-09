import json
from collections.abc import Generator
from typing import Annotated

import pytest

from asgiref.sync import async_to_sync
from dagster_pipes import PipesContext, open_dagster_pipes
from posthoganalytics import Posthog
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from posthog.models import Organization, User
from posthog.ph_client import get_client

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.offline.snapshot_loader import SnapshotLoader
from ee.hogai.eval.schema import DatasetInput, EvalsDockerImageConfig


@pytest.fixture(scope="package")
def dagster_context() -> Generator[PipesContext, None, None]:
    with open_dagster_pipes() as context:
        yield context


class EvaluationContext(BaseModel):
    # We don't want to validate Django models here.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    organization: Annotated[Organization, SkipValidation]
    user: Annotated[User, SkipValidation]
    experiment_name: str
    dataset_id: str
    dataset_name: str
    dataset_inputs: list[DatasetInput]
    client: Posthog | None = Field(default=None)

    def format_experiment_name(self, test_name: str) -> str:
        """Generate a unique experiment name for the given test name."""
        return f"max-ai-{self.experiment_name}-{test_name}"

    def get_callback_handlers(self, test_name: str) -> list[CallbackHandler] | None:
        return [
            CallbackHandler(
                self.client,
                distinct_id="ai_evaluator",
                properties={
                    "dataset_id": self.dataset_id,
                    "dataset_name": self.dataset_name,
                    "ai_experiment_name": self.format_experiment_name(test_name),
                },
            )
        ]


@pytest.fixture(scope="package", autouse=True)
def eval_ctx(
    set_up_evals,  # noqa: F811
    dagster_context: PipesContext,
    django_db_blocker,
) -> Generator[EvaluationContext, None, None]:
    """
    Script that restores dumped Django models and patches AI query runners.
    Creates teams with team_id=project_id for the same single user and organization,
    keeping the original project_ids for teams.
    """
    with django_db_blocker.unblock():
        dagster_context.log.info(f"Loading Postgres and ClickHouse snapshots...")

        posthog_client = get_client("US")

        config = EvalsDockerImageConfig.model_validate(dagster_context.extras)
        loader = SnapshotLoader(dagster_context, config)
        org, user = async_to_sync(loader.load_snapshots)()

        dagster_context.log.info(f"Running tests...")
        yield EvaluationContext(
            organization=org,
            user=user,
            experiment_name=loader.config.experiment_name,
            dataset_id=config.dataset_id,
            dataset_name=config.dataset_name,
            dataset_inputs=config.dataset_inputs,
        )

        posthog_client.shutdown()

        dagster_context.log.info(f"Cleaning up...")
        loader.cleanup()

        dagster_context.log.info(f"Reporting results...")
        with open("eval_results.jsonl") as f:
            lines = f.readlines()
            dagster_context.report_asset_materialization(
                asset_key="evaluation_report",
                metadata={
                    "evaluation_results": [json.loads(line) for line in lines],
                },
            )
