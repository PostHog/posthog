import pytest
from braintrust import EvalCase
from .conftest import MaxEval
from .scorers import ToolRelevance
from ee.hogai.utils.types import AssistantState, AssistantNodeName
from ee.hogai.graph import AssistantGraph
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage, AssistantMessage, AssistantToolCall


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "docs": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .compile()
    )

    def callable(message: str) -> AssistantMessage:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        raw_state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=message)]), {"configurable": {"thread_id": conversation.id}}
        )
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
def eval_root(call_node):
    MaxEval(
        experiment_name="root",
        data=[
            EvalCase(
                input="Create an SQL insight to calculate active users recently",
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
            EvalCase(
                input="Write SQL to calculate active users recently",
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
        ],
        task=call_node,
        scores=[ToolRelevance(semantic_similarity_args={"query_description"})],
    )
