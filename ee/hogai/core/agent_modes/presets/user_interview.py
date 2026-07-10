from dataclasses import replace
from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_CREATE_TOPIC_BY_EMAILS = """
User: Set up an interview about the new dashboard onboarding with alice@acme.com and bob@acme.com
Assistant: I'll create an interview topic about the dashboard onboarding flow targeting those two users.
*Uses create_user_interview_topic with topic, interviewee_emails, and 3-5 open-ended questions*
The topic is created — you can send invites from the topic page.
""".strip()

POSITIVE_EXAMPLE_CREATE_TOPIC_BY_EMAILS_REASONING = """
The assistant used create_user_interview_topic because:
1. The user wants live AI voice interviews, not an in-app survey
2. Participant emails are provided directly, so no cohort/persons lookup is needed
3. The assistant drafts conversational, open-ended questions in topic order
""".strip()

POSITIVE_EXAMPLE_CREATE_TOPIC_FROM_COHORT = """
User: Talk to users in the "Power users" cohort about how they use saved insights
Assistant: I'll first resolve the cohort to distinct IDs, then create the interview topic.
*Creates todo list with the following items:*
1. Search for the "Power users" cohort and resolve its members to distinct IDs
2. Create the interview topic with those distinct IDs and a question list
*Uses search with kind: "cohorts" and query: "Power users"*
After resolving members, the assistant calls create_user_interview_topic with interviewee_distinct_ids.
""".strip()

POSITIVE_EXAMPLE_CREATE_TOPIC_FROM_COHORT_REASONING = """
The assistant used the todo list because:
1. Targeting by cohort needs two steps: resolve the cohort, then create the topic
2. create_user_interview_topic accepts distinct IDs or emails but does not look up cohorts itself
3. Breaking it into steps prevents inventing or mis-targeting participants
""".strip()

POSITIVE_EXAMPLE_ANALYZE_INTERVIEWS = """
User: What patterns are coming out of our recent user interviews?
Assistant: I'll analyze the interview summaries for common themes.
*Uses analyze_user_interviews with an analysis_angle describing the question*
Here are the themes I found across the interviews: ...
""".strip()

POSITIVE_EXAMPLE_ANALYZE_INTERVIEWS_REASONING = """
The assistant used analyze_user_interviews because:
1. The user wants insights from already-conducted interviews, not to create a new topic
2. The tool reads existing interview summaries for the team
3. The analysis_angle steers the LLM toward the user's question
""".strip()


USER_INTERVIEW_MODE_DESCRIPTION = (
    "Specialized mode for setting up and analyzing live AI voice user interviews. "
    "Use this mode when the user wants to interview users, talk to customers, run user research "
    "calls, or analyze interview transcripts. This is NOT a survey mode — interviews are live "
    "voice conversations, not in-app survey widgets."
)


class UserInterviewAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_CREATE_TOPIC_BY_EMAILS,
            reasoning=POSITIVE_EXAMPLE_CREATE_TOPIC_BY_EMAILS_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_CREATE_TOPIC_FROM_COHORT,
            reasoning=POSITIVE_EXAMPLE_CREATE_TOPIC_FROM_COHORT_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ANALYZE_INTERVIEWS,
            reasoning=POSITIVE_EXAMPLE_ANALYZE_INTERVIEWS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.user_interviews.backend.facade.max_tools import (
            AnalyzeUserInterviewsTool,
            CreateUserInterviewTopicTool,
        )

        tools: list[type[MaxTool]] = [CreateUserInterviewTopicTool, AnalyzeUserInterviewsTool]
        return tools


user_interview_agent = AgentModeDefinition(
    mode=AgentMode.USER_INTERVIEW,
    mode_description=USER_INTERVIEW_MODE_DESCRIPTION,
    toolkit_class=UserInterviewAgentToolkit,
)


class ReadOnlyUserInterviewAgentToolkit(AgentToolkit):
    """User interview toolkit for subagents — only includes AnalyzeUserInterviewsTool (read-only)."""

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.user_interviews.backend.facade.max_tools import AnalyzeUserInterviewsTool

        return [AnalyzeUserInterviewsTool]


READ_ONLY_USER_INTERVIEW_MODE_DESCRIPTION = (
    "Specialized mode for analyzing user interviews. Read summaries of past interviews to extract "
    "themes, pain points, and feature requests."
)

subagent_user_interview_agent = replace(
    user_interview_agent,
    toolkit_class=ReadOnlyUserInterviewAgentToolkit,
    mode_description=READ_ONLY_USER_INTERVIEW_MODE_DESCRIPTION,
)

chat_agent_plan_user_interview_agent = AgentModeDefinition(
    mode=AgentMode.USER_INTERVIEW,
    mode_description=READ_ONLY_USER_INTERVIEW_MODE_DESCRIPTION,
    toolkit_class=ReadOnlyUserInterviewAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
