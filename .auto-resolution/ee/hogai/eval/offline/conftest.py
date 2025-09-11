from collections.abc import Generator
from typing import Annotated

import pytest

from asgiref.sync import async_to_sync
from dagster_pipes import PipesContext, open_dagster_pipes
from pydantic import BaseModel, ConfigDict, SkipValidation

from posthog.models import Organization, User

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.offline.snapshot_loader import SnapshotLoader
from ee.hogai.eval.schema import DatasetInput


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
    dataset: list[DatasetInput]


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
