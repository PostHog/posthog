import json
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import pytest

from django.conf import settings

from asgiref.sync import async_to_sync
from autoevals import Score
from autoevals.oai import LLMClient
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


class TracedLLMClient(LLMClient):
    """Fixed LLMClient that preserves the passed methods. autoevals has a bug (or not) that makes it overwrite the methods."""

    def __post_init__(self):
        pass


class EvaluationContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)  # We don't want to validate Django models here.

    organization: Annotated[Organization, SkipValidation]
    user: Annotated[User, SkipValidation]
    experiment_id: str
    experiment_name: str
    dataset_id: str
    dataset_name: str
    dataset_inputs: list[DatasetInput]
    client: Posthog | None = Field(default=None)

    @property
    def distinct_id(self) -> str:
        return "ai_evaluator"

    @property
    def formatted_experiment_name(self) -> str:
        """Generate a unique experiment name for the given test name."""
        test_name = get_eval_context().test_name
        return f"max-ai-{self.experiment_name}-{test_name}"

    def get_callback_handlers(self, trace_id: UUID | str | None) -> list[CallbackHandler]:
        return [
            CallbackHandler(
                self.client,
                trace_id=trace_id,
                distinct_id=self.distinct_id,
                properties=self.properties_for_tracing,
            )
        ]

    @property
    def properties_for_tracing(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "ai_experiment_id": self.experiment_id,
            "ai_experiment_name": self.formatted_experiment_name,
        }

    def get_openai_client_for_tracing(self, trace_id: UUID | str | None) -> TracedLLMClient:
        """Override the OpenAI client to inject tracing parameters."""
        client = AsyncOpenAI(posthog_client=self.client, base_url=settings.OPENAI_BASE_URL)
        original_create = client.chat.completions.create

        async def patched_create(*args, **kwargs):
            # Inject the tracing parameters
            kwargs.setdefault(
                "posthog_properties",
                {
                    **self.properties_for_tracing,
                    "$ai_trace_id": trace_id,
                    "$ai_parent_id": trace_id,
                    "$ai_span_name": "Scorer",
                },
            )
            kwargs.setdefault("posthog_distinct_id", self.distinct_id)
            return await original_create(*args, **kwargs)

        client.chat.completions.create = patched_create  # type: ignore

        return TracedLLMClient(
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
            experiment_id=config.experiment_id,
            experiment_name=config.experiment_name,
            dataset_id=config.dataset_id,
            dataset_name=config.dataset_name,
            dataset_inputs=config.dataset_inputs,
            client=posthog_client,
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


def capture_score(func: Callable[..., Awaitable[Score]]):
    """Decorator that wraps scorer functions to capture the score result."""

    @wraps(func)
    async def wrapper(input: DatasetInput, *args, **kwargs):
        context = get_eval_context()
        score = await func(input, *args, **kwargs)
        if context.client is not None:
            context.client.capture(
                event="$ai_metric",
                properties={
                    "$ai_trace_id": input.trace_id,
                    "$ai_metric_name": score.name,
                    "$ai_metric_value": str(score.score) if score.score is not None else "None",
                    "ai_score_metadata": score.metadata,
                },
            )
        return score

    return wrapper


def with_eval_context(func):
    """Decorator that sets the evaluation context for the test."""

    @wraps(func)
    async def wrapper(eval_ctx: EvaluationContext, *args, **kwargs):
        with set_eval_context(eval_ctx, func.__name__):
            return await func(eval_ctx, *args, **kwargs)

    return wrapper


# Apply decorators to all tests in the package.
def pytest_collection_modifyitems(items):
    """
    One test file might contain multiple evaluation tests cases.
    This hook will automatically apply the local evaluation context to all of them.
    """
    current_dir = Path(__file__).parent
    for item in items:
        if Path(item.fspath).is_relative_to(current_dir):
            item.obj = with_eval_context(item.obj)
