import os
from collections.abc import Generator

import pytest

from braintrust_langchain import BraintrustCallbackHandler, set_global_handler
from langchain_core.runnables import RunnableConfig

from posthog.schema import FailureMessage, HumanMessage

from posthog.models import Organization, Team, User

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.utils import unwrap_visualization_artifact_content
from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer

# We want the PostHog set_up_evals fixture here
from ee.hogai.eval.conftest import set_up_evals  # noqa: F401
from ee.hogai.eval.data_setup import (
    EVAL_USER_FULL_NAME,  # noqa: F401 — re-exported for eval_root_style.py
    DashboardWithInsightsFixture,
    create_core_memory,
    create_dashboard_with_insights,
    create_demo_org_team_user,
)
from ee.hogai.eval.scorers import PlanAndQueryOutput
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.hogai.utils.types.base import ArtifactRefMessage
from ee.models.assistant import Conversation, CoreMemory

handler = BraintrustCallbackHandler()
if os.environ.get("BRAINTRUST_API_KEY") and os.environ.get("EVAL_MODE") != "offline":
    set_global_handler(handler)


@pytest.fixture
def call_root_for_insight_generation(demo_org_team_user):
    # This graph structure will first get a plan, then generate the SQL query.
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root()
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(
        query_with_extra_context: str | tuple[str, str],
    ) -> PlanAndQueryOutput:
        # If query_with_extra_context is a tuple, the first element is the query, the second is the extra context
        # in case there's an ask_user tool call.
        query = query_with_extra_context[0] if isinstance(query_with_extra_context, tuple) else query_with_extra_context
        # Initial state for the graph
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Answer this question: {query}")],
        )
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        # Invoke the graph. The state will be updated through planner and then generator.
        config = RunnableConfig(configurable={"thread_id": conversation.id})
        final_state_raw = await graph.ainvoke(initial_state, config)

        final_state = AssistantState.model_validate(final_state_raw)

        # If we have extra context for the potential ask_user tool, and there's no message of type ai/failure
        # or artifact, we should answer with that extra context. We only do this once at most in an eval case.
        if isinstance(query_with_extra_context, tuple) and not any(
            isinstance(m, ArtifactRefMessage | FailureMessage) for m in final_state.messages
        ):
            final_state.messages = [
                *final_state.messages,
                HumanMessage(content=query_with_extra_context[1]),
            ]
            final_state.graph_status = "resumed"
            final_state_raw = await graph.ainvoke(final_state, config)
            final_state = AssistantState.model_validate(final_state_raw)

        # The order is a viz message, tool call message, and assistant message.
        if (
            not final_state.messages
            or not len(final_state.messages) >= 3
            or not isinstance(final_state.messages[-3], ArtifactRefMessage)
        ):
            return {
                "plan": None,
                "query": None,
                "query_generation_retry_count": final_state.query_generation_retry_count,
            }

        artifact_manager = ArtifactManager(team=demo_org_team_user[1], user=demo_org_team_user[2], config=config)
        enriched_message = await artifact_manager.aenrich_message(final_state.messages[-3])
        content = unwrap_visualization_artifact_content(enriched_message)
        if content is None:
            return {
                "plan": None,
                "query": None,
                "query_generation_retry_count": final_state.query_generation_retry_count,
            }
        return {
            "plan": content.description,
            "query": content.query,
            "query_generation_retry_count": final_state.query_generation_retry_count,
        }

    yield callable


@pytest.fixture(scope="session", autouse=True)
def demo_org_team_user(
    set_up_evals,  # noqa: F811
    django_db_blocker,
) -> Generator[tuple[Organization, Team, User], None, None]:
    yield create_demo_org_team_user(django_db_blocker)


@pytest.fixture(scope="session", autouse=True)
def core_memory(demo_org_team_user, django_db_blocker) -> Generator[CoreMemory, None, None]:
    yield create_core_memory(demo_org_team_user[1], django_db_blocker)


@pytest.fixture
def dashboard_with_insights(
    demo_org_team_user,
) -> Generator[DashboardWithInsightsFixture, None, None]:
    """Creates a dashboard with 3 insights and 1 replacement insight for testing UpsertDashboardTool."""
    yield create_dashboard_with_insights(*demo_org_team_user)
    # No manual cleanup needed - Django's test framework handles rollback automatically
