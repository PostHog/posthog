import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, AssistantState

from ..base import MaxPublicEval


class TicketRouting(LLMClassifier):
    """Judge whether a request phrased in words reaches the support ticket command."""

    def __init__(self, **kwargs):
        super().__init__(
            name="ticket_routing",
            prompt_template="""
A customer asked PostHog AI for something. Judge whether the reply routes them to the right place.

<user_message>
{{{input}}}
</user_message>

<assistant_response>
{{{output.content}}}
</assistant_response>

What the reply should do:
{{expected}}

Choose one:
- pass: the reply does what is described above
- fail: the reply does something else, in particular when it drafts or offers to open an issue in an
  external tracker for a problem with PostHog, or when it answers a request about the customer's own
  product with the PostHog support ticket command
""".strip(),
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
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
async def eval_ticket_routing(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="ticket_routing",
        task=call_root,
        scores=[TicketRouting()],
        data=[
            EvalCase(
                input="this tool in my traces keeps failing and I have got nowhere with it. can you create an issue about it",
                expected="Offer the `/ticket` command so PostHog support picks the problem up. It must not draft an issue for GitHub, Jira, Linear, or any other tracker.",
            ),
            EvalCase(
                input="please file a bug for this with your team",
                expected="Offer the `/ticket` command, and say it creates a support ticket from this conversation.",
            ),
            EvalCase(
                input="I want a human at PostHog to look at this, how do I escalate it",
                expected="Point to the `/ticket` command, or to in-app support for a billing problem. It must not send them to an external tracker.",
            ),
            EvalCase(
                input="open an issue in Linear for my team about the broken checkout page in our app",
                expected="Treat this as work in the customer's own tracker about their own product. It must not offer the `/ticket` command, which creates a PostHog support ticket.",
            ),
        ],
        pytestconfig=pytestconfig,
    )
