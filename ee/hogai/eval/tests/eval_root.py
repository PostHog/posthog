# ruff: noqa: E402

import pytest

from autoevals.partial import ScorerWithPartial
from autoevals.ragas import AnswerSimilarity

from braintrust import Eval, Score
from ee.hogai.utils.types import AssistantState, AssistantNodeName
from ee.hogai.graph import AssistantGraph
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage, AssistantMessage, AssistantToolCall
from braintrust import init_logger

BRAINTRUST_PROJECT_NAME = "Max AI"

init_logger(BRAINTRUST_PROJECT_NAME)


class ToolRelevance(ScorerWithPartial):
    semantic_similarity_args: set[str]

    def __init__(self, *, semantic_similarity_args: set[str]):
        self.semantic_similarity_args = semantic_similarity_args

    def _run_eval_sync(self, output, expected, **kwargs):
        assert isinstance(expected, AssistantToolCall)
        assert isinstance(output, AssistantMessage)
        if output.tool_calls and len(output.tool_calls) > 1:
            raise ValueError("Parallel tool calls not supported by this scorer yet")
        score = 0.0  # 0.0 to 1.0
        if output.tool_calls and len(output.tool_calls) == 1:
            tool_call = output.tool_calls[0]
            # 0.5 point for getting the tool right
            if tool_call.name == expected.name:
                score += 0.5
                score_per_arg = 0.5 / len(expected.args)
                for arg_name, expected_arg_value in expected.args.items():
                    if arg_name in self.semantic_similarity_args:
                        arg_similarity = AnswerSimilarity(model="text-embedding-3-small").eval(
                            output=tool_call.args.get(arg_name), expected=expected_arg_value
                        )
                        score += arg_similarity.score * score_per_arg
                    elif tool_call.args.get(arg_name) == expected_arg_value:
                        score += score_per_arg
        return Score(name=self._name(), score=score)


@pytest.fixture
def call_node(org_team_user):
    graph = (
        AssistantGraph(org_team_user[1])
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
        conversation = Conversation.objects.create(team=org_team_user[1], user=org_team_user[2])
        raw_state = graph.invoke(
            AssistantState(messages=[HumanMessage(content=message)]),
            {
                "configurable": {
                    "thread_id": conversation.id,
                }
            },
        )
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
def eval_root(call_node):
    Eval(
        BRAINTRUST_PROJECT_NAME,
        data=[
            {
                "input": "Create an SQL insight to calculate active users recently",
                "expected": AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            },
            {
                "input": "Write SQL to calculate active users recently",
                "expected": AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            },
        ],
        task=call_node,
        scores=[ToolRelevance(semantic_similarity_args={"query_description"})],
    )
