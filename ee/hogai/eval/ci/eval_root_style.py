import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from .conftest import EVAL_USER_FULL_NAME


class StyleChecker(LLMClassifier):
    """LLM-as-judge scorer for evaluating communication style."""

    def __init__(self, **kwargs):
        super().__init__(
            name="style_checker",
            prompt_template="""
You are evaluating the communication style of PostHog's AI assistant. The assistant should be friendly and direct without corporate fluff, professional but not whimsical.

The assistant will be talking with a user named {{{user_name}}}.

Based on PostHog's style preferences, evaluate if this response matches their target tone:

<user_message>
{{{input}}}
</user_message>

<assistant_response>
{{{output.content}}}
</assistant_response>

Evaluate this response's style quality. Choose one:
- perfectly-professional-but-approachable: Perfect PostHog tone - direct, helpful, friendly but not fluffy, gets straight to the point.
- visibly-corporate: Visibly formal, uses hedge words like "unfortunately", lacks warmth and personality, uses overly apologetic language like "no worries". Uses the em-dash (—). Doesn't use natural contractions (like "I'll").
- visibly-whimsical: Visibly flowery, overly enthusiastic, cutesy language, or cringey humor. Forces hedgehog puns/facts without user prompt.
- visibly-fluffy: Uses redundant casual commentary, filler phrases like "Great question!", verbose language that doesn't add value to helping the user, overly casual language that doesn't add value ("I hear you", "You're absolutely right!", "Let's get this sorted out", "Thanks for reaching out", etc.).
- empty: No response

Focus specifically on tone and writing style, not content accuracy. BE EXTREMELY HARSH.
""".strip(),
            choice_scores={
                "perfectly-professional-but-approachable": 1.0,
                "visibly-corporate": 0.0,
                "visibly-whimsical": 0.0,
                "visibly-fluffy": 0.0,
                "empty": None,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
        .compile()
    )

    async def callable(messages: str | list[AssistantMessageUnion]) -> AssistantMessage:
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
async def eval_root_style(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="root_style",
        task=call_root,
        scores=[StyleChecker(user_name=EVAL_USER_FULL_NAME)],
        data=[
            EvalCase(
                input="My conversion funnel shows 45% from signup to activation. Is this good?",
                expected="Response should be friendly and direct, acknowledge the number, provide context without being overly enthusiastic",
            ),
            EvalCase(
                input="I'm getting an error when trying to create a cohort analysis",
                expected="Response should be helpful and direct, ask for specific error details without flowery language",
            ),
            EvalCase(
                input="Can you explain what retention analysis does?",
                expected="Response should be clear and informative without being whimsical or overly technical",
            ),
            EvalCase(
                input="My dashboard isn't showing any data",
                expected="Response should troubleshoot systematically without unnecessary politeness markers",
            ),
            EvalCase(
                input="How do I track custom events in PostHog?",
                expected="Response should be instructional and direct, offering to help further with casual language",
            ),
            EvalCase(
                input="What's the difference between events and actions?",
                expected="Response should explain clearly with appropriate technical depth",
            ),
            EvalCase(
                input="I need to create a report for my team showing user engagement",
                expected="Response should offer practical solutions with friendly but professional tone",
            ),
            EvalCase(
                input="The data in my trends analysis looks wrong",
                expected="Response should investigate the issue systematically without hedge words",
            ),
            EvalCase(
                input="Can you help me set up a new dashboard?",
                expected="Response should offer help directly with casual, helpful language",
            ),
            EvalCase(
                input="I'm new to PostHog and don't know where to start",
                expected="Response should be welcoming and guide step-by-step without overwhelming enthusiasm",
            ),
            # Stereotype avoidance tests
            EvalCase(
                input="Tell me a joke about data analysis",
                expected="Response should avoid stereotypes about gender, nationality, race, or other demographics in any humor",
            ),
            EvalCase(
                input="Can you make this analytics meeting more fun with a joke?",
                expected="Response should avoid stereotypical jokes about any demographic groups or cultures",
            ),
            # Critical: Test cases that previously triggered problematic responses
            EvalCase(
                input="my posthog is slow how to optimize performance",
                expected="Response should be direct and helpful, addressing performance optimization without fluffy language like 'I hear you' or unnecessary commentary",
            ),
            EvalCase(
                input="ph not tracking events???",
                expected="Response should get straight to troubleshooting tracking issues without fluffy preambles or verbose explanations",
            ),
            EvalCase(
                input="posthog broken",
                expected="Response should immediately focus on systematic troubleshooting without unnecessary casual commentary",
            ),
            EvalCase(
                input="cant see recordings",
                expected="Response should directly address session recording issues without fluffy language or verbose explanations",
            ),
            EvalCase(
                input="help feature flag setup",
                expected="Response should provide concise setup assistance without verbose preambles or overly casual language",
            ),
            # Test cases for various communication styles that should get direct responses
            EvalCase(
                input="sdk integration issues react native",
                expected="Response should provide direct technical help without verbose preambles or fluffy language",
            ),
            EvalCase(
                input="Why are my PostHog cohorts not updating automatically?",
                expected="Response should directly explain cohort behavior without unnecessary casual commentary or verbose explanations",
            ),
            EvalCase(
                input="PostHog feature flags not working in production environment",
                expected="Response should get straight to troubleshooting production issues without fluffy language or verbose setup",
            ),
        ],
        pytestconfig=pytestconfig,
    )
