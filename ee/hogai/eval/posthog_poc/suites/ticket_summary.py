from __future__ import annotations

import pytest

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

from ..judge import ChoiceJudgeScorer
from ..types import EvalCase, EvalSuite

TICKET_SUMMARY_SCORER = ChoiceJudgeScorer(
    metric_name="ticket_summary_quality",
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
- fail: Wrong format, missing sections, uses first person, includes bullets, misses major information, or empty/meaningless output
""",
    choice_scores={
        "pass": 1.0,
        "fail": 0.0,
    },
)

TICKET_SUMMARY_CASES = [
    EvalCase(
        id="ticket-summary-1",
        name="funnel with no data",
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
        expected=(
            "Issue section should mention funnel creation, $pageview and purchase_completed events, 'No data' problem. "
            "Status section should mention PostHog AI verified events exist, suggested date range changes, issue remains unresolved."
        ),
    ),
    EvalCase(
        id="ticket-summary-2",
        name="cohort property type resolved",
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
        expected=(
            "Issue section should mention cohort creation error, 'Invalid property type' message, filtering by email with "
            "@company.com. Status section should mention PostHog AI suggested using 'contains' filter, issue was resolved."
        ),
    ),
]


@pytest.fixture
def call_ticket_summary_summarizer(demo_org_team_user):
    async def callable(conversation: list[dict[str, str]]) -> str:
        messages_list: list[SystemMessage | LangchainHumanMessage | AIMessage] = [
            SystemMessage(content=SUPPORT_SUMMARIZER_SYSTEM_PROMPT)
        ]

        for message in conversation:
            if message["role"] == "human":
                messages_list.append(LangchainHumanMessage(content=message["content"]))
            elif message["role"] == "assistant":
                messages_list.append(AIMessage(content=message["content"]))

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


def build_ticket_summary_suite(task) -> EvalSuite:
    return EvalSuite(
        experiment_name="ticket_summary",
        task=task,
        cases=TICKET_SUMMARY_CASES,
        metrics=[TICKET_SUMMARY_SCORER.as_metric()],
    )
