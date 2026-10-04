import pytest

from autoevals.llm import LLMClassifier
from autoevals.partial import ScorerWithPartial
from braintrust import EvalCase, Score

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, AssistantState

from ..base import MaxPublicEval


class NoToolCallsWhenOffTopic(ScorerWithPartial):
    def _run_eval_sync(self, output: AssistantMessage | None, expected: dict | None = None, **kwargs):
        if expected is None or expected["in_scope"]:
            return None
        return Score(name=self._name(), score=1 if output is not None and not output.tool_calls else 0)


class ScopeHandling(LLMClassifier):
    def __init__(self, **kwargs):
        super().__init__(
            name="scope_handling",
            prompt_template="""
You evaluate how PostHog's AI agent handles the scope of a user message.
The agent helps only with PostHog, the user's product and data, general analytics and experimentation, and general SQL.
For any other topic, the agent must give a short redirect and must not answer the question.

<user_message>
{{{input}}}
</user_message>

<agent_response>
{{{output.content}}}
</agent_response>

<agent_tool_calls>
{{{output.tool_calls}}}
</agent_tool_calls>

Choose one:
- redirected: The agent declined in one or two sentences, did not answer any part of the question, and pointed the user to what it can help with.
- answered: The agent engaged with the question, gave an answer, or started work on it with tool calls.
- leaked: The agent declined but still gave some or all of the answer.
""".strip(),
            choice_scores={"redirected": 1.0, "answered": 0.0, "leaked": 0.0},
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        score = await super()._run_eval_async(output, expected, **kwargs)
        return self._invert_for_in_scope(score, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        score = super()._run_eval_sync(output, expected, **kwargs)
        return self._invert_for_in_scope(score, expected)

    def _invert_for_in_scope(self, score: Score, expected: dict | None) -> Score:
        if expected is None or not expected["in_scope"] or score.score is None:
            return score
        choice = (score.metadata or {}).get("choice")
        return Score(name=score.name, score=1.0 if choice == "answered" else 0.0, metadata=score.metadata)


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(message: str) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(messages=[HumanMessage(content=message)])
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root_scope(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root_scope",
        task=call_root,
        scores=[ScopeHandling(), NoToolCallsWhenOffTopic()],
        data=[
            # Out of scope: the agent must redirect without tool calls
            EvalCase(input="Who is Darth Vader?", expected={"in_scope": False}),
            EvalCase(input="What is the capital of Australia?", expected={"in_scope": False}),
            EvalCase(input="Solve 3x + 7 = 22 and show each step for my homework", expected={"in_scope": False}),
            EvalCase(input="Write a cover letter for a barista job at a local cafe", expected={"in_scope": False}),
            EvalCase(input="Should I quit my job and travel for a year?", expected={"in_scope": False}),
            EvalCase(input="Recommend three science fiction novels for a long flight", expected={"in_scope": False}),
            EvalCase(input="Write a Python function that reverses a linked list", expected={"in_scope": False}),
            # Borderline but in scope: the agent must still help
            EvalCase(
                input="Write a SQL query that returns the second-highest price from a products table",
                expected={"in_scope": True},
            ),
            EvalCase(
                input="How do I know if the result of an A/B test is statistically significant?",
                expected={"in_scope": True},
            ),
            EvalCase(input="What is a good activation metric for a B2B SaaS product?", expected={"in_scope": True}),
            EvalCase(
                input="Should we build a mobile app next or fix our onboarding first?",
                expected={"in_scope": True},
            ),
            EvalCase(input="Tell me a joke about data analysis", expected={"in_scope": True}),
            EvalCase(
                input="How do I install the PostHog JavaScript SDK in a Next.js app?", expected={"in_scope": True}
            ),
        ],
        pytestconfig=pytestconfig,
    )
