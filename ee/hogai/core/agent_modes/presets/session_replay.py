from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.tools.replay.filter_session_recordings import FilterSessionRecordingsTool
from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool
from ee.hogai.tools.todo_write import TodoWriteExample

from ..factory import AgentModeDefinition
from ..toolkit import AgentToolkit

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

POSITIVE_EXAMPLE_FILTER_WITH_PROPERTIES = """
User: Show me recordings of mobile users from the US who encountered errors
Assistant: I'll help you find those recordings. Let me create a todo list to ensure I discover the right properties and filters.
*Creates todo list with the following items:*
1. Use read_taxonomy to discover person properties for country filtering
2. Use read_taxonomy to discover session properties for device type
3. Use read_taxonomy to discover recording properties for errors
4. Filter session recordings with the discovered properties
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_FILTER_WITH_PROPERTIES_REASONING = """
The assistant used the todo list because:
1. Filtering session recordings requires discovering multiple property types (person, session, recording)
2. Property names and values must be validated through read_taxonomy before creating filters
3. The query involves multiple filter criteria that need to be combined
4. The filter_session_recordings tool documentation explicitly requires using read_taxonomy for property discovery
5. Breaking this into steps ensures all properties are discovered before attempting to filter
""".strip()

POSITIVE_EXAMPLE_SUMMARIZE_WITH_CONTEXT = """
User: Summarize sessions where users clicked the checkout button but didn't complete purchase
Assistant: I'll help you analyze those sessions. This requires multiple steps to ensure we get the right recordings.
*Creates todo list with the following items:*
1. Use read_taxonomy to discover events related to checkout
2. Use read_taxonomy to discover events related to purchase completion
3. Filter session recordings for sessions with checkout events but without purchase events
4. Summarize the filtered sessions to identify patterns and issues
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_SUMMARIZE_WITH_CONTEXT_REASONING = """
The assistant used the todo list because:
1. Session summarization requires filtering first (can't summarize without identifying relevant sessions)
2. The filtering requires discovering event properties through read_taxonomy
3. Complex event-based filters need validation before being used
4. The summarize_sessions tool requires filter_session_recordings to be called first
5. This is a multi-step analysis requiring systematic progression through discovery, filtering, and summarization
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_RECORDING_ANALYSES = """
User: Compare mobile vs desktop user behavior and also check if users with errors have different session patterns
Assistant: I'll help you analyze these different user segments. Let me break this down into separate analyses.
*Creates todo list with the following items:*
1. Filter and summarize mobile user sessions
2. Filter and summarize desktop user sessions
3. Filter and summarize sessions with console errors
4. Filter and summarize sessions without errors
5. Compare findings across segments
*Begins working on the first task*
""".strip()

POSITIVE_EXAMPLE_MULTIPLE_RECORDING_ANALYSES_REASONING = """
The assistant used the todo list because:
1. The user requested multiple separate recording analyses that need distinct filters
2. Each segment (mobile, desktop, errors, no errors) requires its own filter_session_recordings call
3. Each segment needs individual summarization
4. The todo list helps organize these parallel analyses into manageable tasks
5. This approach allows for tracking progress across multiple recording queries and summaries
""".strip()

MODE_DESCRIPTION = "Specialized mode for analyzing session recordings and user behavior. This mode allows you to filter session recordings, and summarize entire sessions or a set of them."


class SessionReplayAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_FILTER_WITH_PROPERTIES,
            reasoning=POSITIVE_EXAMPLE_FILTER_WITH_PROPERTIES_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SUMMARIZE_WITH_CONTEXT,
            reasoning=POSITIVE_EXAMPLE_SUMMARIZE_WITH_CONTEXT_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_MULTIPLE_RECORDING_ANALYSES,
            reasoning=POSITIVE_EXAMPLE_MULTIPLE_RECORDING_ANALYSES_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        tools: list[type[MaxTool]] = [FilterSessionRecordingsTool, SummarizeSessionsTool]
        return tools


session_replay_agent = AgentModeDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=SessionReplayAgentToolkit,
)


chat_agent_plan_session_replay_agent = AgentModeDefinition(
    mode=AgentMode.SESSION_REPLAY,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=SessionReplayAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
