import pytest

from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            path_map={
                "insights": AssistantNodeName.END,
                "billing": AssistantNodeName.END,
                "insights_search": AssistantNodeName.END,
                "search_documentation": AssistantNodeName.END,
                "root": AssistantNodeName.ROOT,
                "end": AssistantNodeName.END,
            },
            tools_node=AssistantNodeName.END,
        )
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(messages):
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root_entity_search(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root_entity_search",
        task=call_root,
        scores=[ToolRelevance(semantic_similarity_args={"query"})],
        data=[
            # Entity search
            EvalCase(
                input="Search for my dashboards about user engagement",
                expected=AssistantToolCall(
                    name="search",
                    args={
                        "kind": "dashboards",
                        "query": "user engagement",
                    },
                    id="call_search_1",
                ),
            ),
            EvalCase(
                input="Search for my cohorts about mobile users",
                expected=AssistantToolCall(
                    name="search",
                    args={
                        "kind": "cohorts",
                        "query": "mobile users",
                    },
                    id="call_search_3",
                ),
            ),
            EvalCase(
                input="Find my feature flags related to the new feature about batch export",
                expected=AssistantToolCall(
                    name="search",
                    args={
                        "kind": "feature_flags",
                        "query": "batch export",
                    },
                    id="call_search_4",
                ),
            ),
            EvalCase(
                input="Search for everything that might be related to `revenue`",
                expected=AssistantToolCall(
                    name="search",
                    args={
                        "kind": "all",
                        "query": "revenue",
                    },
                    id="call_search_5",
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
