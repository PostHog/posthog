import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from langchain_core.messages import (
    AIMessage,
    HumanMessage as LangchainHumanMessage,
    SystemMessage,
)

from ee.hogai.chat_agent.slash_commands.commands.ticket.prompts import (
    SUPPORT_SUMMARIZER_SYSTEM_PROMPT,
    SUPPORT_SUMMARIZER_USER_PROMPT,
)
from ee.hogai.llm import MaxChatAnthropic

from ..base import MaxPublicEval


class TicketSummaryQuality(LLMClassifier):
    """Evaluate ticket summary quality based on the prompt requirements."""

    def __init__(self, **kwargs):
        super().__init__(
            name="ticket_summary_quality",
            prompt_template="""Evaluate if the ticket summary follows the required format and captures the conversation appropriately.

Required format:
- Exactly 2 labeled sections separated by a blank line
- Section 1: "**Issue**:" followed by the user's problem and relevant technical details
- Section 2: "**Status**:" followed by what PostHog AI attempted and the current state

Quality criteria:
1. Has exactly two sections: **Issue:** and **Status:**
2. Uses third person perspective (refers to "the user" not "you" or "I")
3. Refers to itself as "PostHog AI" (not "the AI" or "I")
4. Does NOT include bullet points
5. Does NOT include "Recommended next steps" or similar sections
6. Plain text only, no markdown formatting beyond the section headers
7. **Issue:** captures the user's problem and relevant technical details
8. **Status:** explains what PostHog AI attempted and current state

Generated summary:
<summary>
{{output}}
</summary>

Expected summary characteristics:
{{expected}}

Does this summary pass? Choose one:
- pass: Follows the required format with both sections, captures key information, and follows the rules (minor issues acceptable)
- fail: Wrong format, missing sections, uses first person, includes bullets, misses major information, or empty/meaningless output""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_summarizer(demo_org_team_user):
    async def callable(conversation: list[dict[str, str]]) -> str:
        """Run the summarizer on a conversation."""
        messages_list: list[SystemMessage | LangchainHumanMessage | AIMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT)
        ]

        for msg in conversation:
            if msg["role"] == "human":
                messages_list.append(LangchainHumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages_list.append(AIMessage(content=msg["content"]))

        messages_list.append(LangchainHumanMessage(content=SUPPORT_SUMMARIZER_USER_PROMPT))

        model = MaxChatAnthropic(
            model="claude-haiku-4-5",
            streaming=False,
            user=demo_org_team_user[2],
            team=demo_org_team_user[1],
            max_tokens=2048,
            billable=False,
        )

        response = await model.ainvoke(messages_list)
        content = response.content
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        return content

    return callable


@pytest.mark.django_db
async def eval_ticket_summary(call_summarizer, pytestconfig):
    await MaxPublicEval(
        experiment_name="ticket_summary",
        task=call_summarizer,
        scores=[TicketSummaryQuality()],
        data=[
            EvalCase(
                input=[
                    {"role": "human", "content": "I'm trying to create a funnel but I see no data"},
                    {
                        "role": "assistant",
                        "content": "I can help with that. Let me check your funnel setup. What events are you using in your funnel?",
                    },
                    {"role": "human", "content": "I'm using $pageview and purchase_completed"},
                    {
                        "role": "assistant",
                        "content": "I found those events in your project. The issue might be the date range. Let me check - are you filtering to the last 7 days?",
                    },
                    {"role": "human", "content": "Yes, but I know I have data from the last 7 days"},
                    {
                        "role": "assistant",
                        "content": "I see the events exist. Try extending the date range to 30 days to see if that helps identify the issue.",
                    },
                    {"role": "human", "content": "Still no data showing even with 30 days"},
                ],
                expected="Issue section should mention funnel creation, $pageview and purchase_completed events, 'No data' problem. Status section should mention PostHog AI verified events exist, suggested date range changes, issue remains unresolved.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": "Session recordings aren't capturing clicks in my React app"},
                    {
                        "role": "assistant",
                        "content": "Let me help troubleshoot. What version of posthog-js are you using?",
                    },
                    {"role": "human", "content": "Version 1.96.0 with autocapture enabled"},
                    {
                        "role": "assistant",
                        "content": "That's a recent version. Have you checked that 'Record user sessions' is enabled in your project settings?",
                    },
                    {"role": "human", "content": "Yes it's enabled. Console shows no errors."},
                    {
                        "role": "assistant",
                        "content": "Your SDK initialization looks correct. The clicks should be appearing in the recordings timeline.",
                    },
                    {"role": "human", "content": "They're still not showing up"},
                ],
                expected="Issue section should mention session recordings, clicks not captured, React application, posthog-js 1.96.0, autocapture enabled. Status section should mention PostHog AI verified settings are correct, SDK initialization checked, issue unresolved.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": "How do I track revenue in PostHog?"},
                    {
                        "role": "assistant",
                        "content": "You can track revenue by capturing events with a revenue property. For example, capture a 'purchase' event with an 'amount' property.",
                    },
                    {"role": "human", "content": "Got it, thanks!"},
                ],
                expected="Issue section should mention user asking about revenue tracking. Status section should mention PostHog AI explained how to track revenue with events and properties, question was answered successfully.",
            ),
            EvalCase(
                input=[
                    {
                        "role": "human",
                        "content": "I'm getting an error when trying to create a cohort based on user properties",
                    },
                    {
                        "role": "assistant",
                        "content": "What error message are you seeing?",
                    },
                    {
                        "role": "human",
                        "content": "It says 'Invalid property type' when I try to filter by email containing @company.com",
                    },
                    {
                        "role": "assistant",
                        "content": "This error usually occurs when the property hasn't been properly indexed. Let me check your property definitions.",
                    },
                    {"role": "human", "content": "I set email as a string property"},
                    {
                        "role": "assistant",
                        "content": "I can see the email property. Try using 'contains' instead of 'equals' for the filter.",
                    },
                    {"role": "human", "content": "That worked! Thanks!"},
                ],
                expected="Issue section should mention cohort creation error, 'Invalid property type' message, filtering by email with @company.com. Status section should mention PostHog AI suggested using 'contains' filter, issue was resolved.",
            ),
            EvalCase(
                input=[
                    {"role": "human", "content": "My feature flags aren't working on mobile"},
                    {
                        "role": "assistant",
                        "content": "Are you using the iOS SDK, Android SDK, or React Native?",
                    },
                    {"role": "human", "content": "React Native with posthog-react-native 3.0.0"},
                    {
                        "role": "assistant",
                        "content": "Have you called posthog.reloadFeatureFlags() after initialization?",
                    },
                    {"role": "human", "content": "No, let me try that"},
                    {
                        "role": "assistant",
                        "content": "Feature flags are fetched asynchronously so you may need to wait for them to load.",
                    },
                    {"role": "human", "content": "Added that but still not working"},
                ],
                expected="Issue section should mention feature flags not working, React Native, posthog-react-native 3.0.0. Status section should mention PostHog AI suggested reloadFeatureFlags(), async loading considerations, issue unresolved.",
            ),
        ],
        pytestconfig=pytestconfig,
    )
