import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from posthog.schema import AssistantMessage, HumanMessage

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState

from ..base import MaxPublicEval


class LanguageMatchChecker(LLMClassifier):
    """LLM-as-judge scorer for evaluating whether the assistant replied in the user's language."""

    def __init__(self, **kwargs):
        super().__init__(
            name="language_match_checker",
            prompt_template="""
You are checking whether PostHog's AI assistant replied in the same language as the user's most recent message.

<user_message>
{{{input}}}
</user_message>

<assistant_response>
{{{output.content}}}
</assistant_response>

<user_message> may be a single message, or a full conversation transcript ending in the user's latest message. It may be rendered with Python object syntax like `HumanMessage(content="...", type="human")` - that syntax is formatting, not part of the message.
Identify the language of the user's MOST RECENT message only, ignoring the language of any earlier turns in the transcript, then judge whether the assistant's response is written in that same language.
Ignore product names, proper nouns, and any code or query snippets when judging language - only assess the natural-language prose.

Choose one:
- matches: The response's prose is in the same language as the user's most recent message.
- mismatches: The response's prose is in a different language than the user's most recent message.
- empty: No response.
""".strip(),
            choice_scores={
                "matches": 1.0,
                "mismatches": 0.0,
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
async def eval_response_language(call_root, pytestconfig):
    await MaxPublicEval(
        experiment_name="response_language",
        task=call_root,
        scores=[LanguageMatchChecker()],
        data=[
            EvalCase(
                input="Wie viele Nutzer haben sich letzte Woche angemeldet?",
                expected="Response prose should be in German",
            ),
            EvalCase(
                input="Quantos usuários visitaram meu site ontem?",
                expected="Response prose should be in Portuguese",
            ),
            EvalCase(
                input="¿Cuál es mi tasa de conversión de registro a activación?",
                expected="Response prose should be in Spanish",
            ),
            EvalCase(
                input="Peux-tu m'expliquer ce que fait l'analyse de rétention ?",
                expected="Response prose should be in French",
            ),
            EvalCase(
                input="今週のアクティブユーザー数を教えてください",
                expected="Response prose should be in Japanese",
            ),
            # A conversation that started in English but switches language mid-thread should follow the latest message
            EvalCase(
                input=[
                    HumanMessage(content="How many users signed up last month?"),
                    AssistantMessage(content="You had 1,204 signups last month."),
                    HumanMessage(content="Und wie viele davon sind aktiv geblieben?"),
                ],
                expected="Response prose should be in German, matching the latest message, even though the conversation started in English",
            ),
        ],
        pytestconfig=pytestconfig,
    )
