import json
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Annotated, Any
from uuid import UUID

import pytest

from asgiref.sync import async_to_sync
from autoevals.llm import LLMClient
from dagster_pipes import PipesContext, open_dagster_pipes
from openai import RateLimitError
from posthoganalytics import Posthog
from posthoganalytics.ai.langchain.callbacks import CallbackHandler
from posthoganalytics.ai.openai.openai_async import AsyncOpenAI
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

    @property
    def formatted_experiment_name(self) -> str:
        """Generate a unique experiment name for the given test name."""
        test_name = get_eval_context().test_name
        return f"max-ai-{self.experiment_name}-{test_name}"

    @property
    def callback_handlers(self) -> list[CallbackHandler] | None:
        return [
            CallbackHandler(
                self.client,
                distinct_id="ai_evaluator",
                properties=self.properties_for_tracing,
            )
        ]

    @property
    def properties_for_tracing(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "ai_experiment_name": self.formatted_experiment_name,
        }

    def get_openai_client_for_tracing(self, trace_id: UUID) -> AsyncOpenAI:
        """Override the OpenAI client to inject tracing parameters."""
        client = AsyncOpenAI(posthog_client=self.client)
        original_create = client.chat.completions.create

        async def patched_create(*args, **kwargs):
            # Inject the tracing parameters
            kwargs.setdefault("posthog_trace_id", trace_id)
            kwargs.setdefault("posthog_properties", self.properties_for_tracing)
            return await original_create(*args, **kwargs)

        client.completions.create = patched_create  # type: ignore

        return LLMClient(
            openai=client,
            complete=patched_create,
            embed=client.embeddings.create,
            moderation=client.moderations.create,
            is_async=True,
            RateLimitError=RateLimitError,
        )


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


class LocalEvaluationContext(EvaluationContext):
    test_name: str


_scoped_eval_context: ContextVar[LocalEvaluationContext] = ContextVar("eval_context")


@contextmanager
def set_eval_context(context: EvaluationContext, test_name: str):
    """Set the local eval context for the duration of the context manager."""
    token = _scoped_eval_context.set(LocalEvaluationContext(**context.model_dump(), test_name=test_name))
    try:
        yield
    finally:
        _scoped_eval_context.reset(token)


def get_eval_context() -> LocalEvaluationContext:
    """Get the local eval context. Raises `LookupError` if no context is set."""
    return _scoped_eval_context.get()
