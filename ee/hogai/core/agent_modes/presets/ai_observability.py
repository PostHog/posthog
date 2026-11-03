from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import ChatAgentPlanExecutable, ChatAgentPlanToolsExecutable
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.search_traces import SearchLLMTracesTool
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_SEARCH_TRACES = """
User: Show me recent LLM traces
Assistant: I'll search for recent LLM traces from the past week.
*Uses search_llm_traces with dateRange: { date_from: "-7d" }*
""".strip()

POSITIVE_EXAMPLE_SEARCH_TRACES_REASONING = """
The assistant used the search tool because:
1. The user wants to see recent traces
2. The search_llm_traces tool can filter by date range
3. This is a straightforward search that doesn't require multiple steps
""".strip()

POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE = """
User: What's happening in my most expensive trace?
Assistant: I'll find the most expensive trace and then analyze it in detail.
*Creates todo list with the following items:*
1. Search for the most expensive trace
2. Read the trace details
3. Explain what happened
*Uses search_llm_traces with limit: 1 and ordered by cost*
After getting the trace, the assistant uses read_data with kind: "llm_trace" to get full details, then explains what happened.
""".strip()

POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE_REASONING = """
The assistant used the todo list because:
1. The user wants to understand the most expensive trace, not just see a list
2. This requires multiple steps: search to find it, read to get details, then explain
3. Breaking this into steps ensures the assistant gets all necessary data before explaining
""".strip()

POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL = """
User: Write a Hog eval that checks if the output is longer than 10 characters
Assistant: I'll write a Hog evaluation and test it against your recent events.
*Uses run_hog_eval_test with source: 'let result := length(output) > 10; print(concat("Output length: ", toString(length(output)))); return result;'*
""".strip()

POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL_REASONING = """
The assistant used run_hog_eval_test because:
1. The user wants to create a Hog evaluation that checks output length
2. The tool compiles and runs the code against real events to verify it works
3. The results show whether the evaluation logic is correct
""".strip()

POSITIVE_EXAMPLE_FIX_EVAL_ERRORS = """
User: The eval is failing with a null error on some events
Assistant: I'll fix the null handling and test again.
*Uses run_hog_eval_test with updated source that adds null checks*
After seeing the results, the assistant explains what was fixed.
""".strip()

POSITIVE_EXAMPLE_FIX_EVAL_ERRORS_REASONING = """
The assistant used run_hog_eval_test because:
1. The user reported errors in the evaluation code
2. Testing with the tool reveals which events cause null errors
3. The assistant can iterate on the fix by running the tool again
""".strip()

POSITIVE_EXAMPLE_DISCOVER_SKILL = """
User: Audit my error tracking issues for last week
Assistant: I'll check whether the team already has a shared skill that covers this audit, then follow it.
*Uses list_llm_skills with search: "error tracking"*
*Finds "audit-error-tracking" — uses get_llm_skill with skill_name: "audit-error-tracking" to load the body*
*Follows the workflow steps defined in the SKILL.md body*
""".strip()

POSITIVE_EXAMPLE_DISCOVER_SKILL_REASONING = """
The assistant used list_llm_skills + get_llm_skill because:
1. The user asked for a multi-step workflow (an "audit") — exactly the kind of recipe that's often saved as a skill
2. Following a team skill stays consistent with how the team has previously asked for the same task
3. Discovery is cheap: list_llm_skills returns just names + descriptions, so the assistant can scan and only load the relevant body
""".strip()

POSITIVE_EXAMPLE_SAVE_SKILL = """
User: Save this workflow as a shared skill called "audit-error-tracking"
Assistant: I'll save it as a shared skill so the whole team can reuse it.
*Uses create_llm_skill with name: "audit-error-tracking", a clear description, and the body summarizing the workflow we just walked through*
""".strip()

POSITIVE_EXAMPLE_SAVE_SKILL_REASONING = """
The assistant used create_llm_skill because:
1. The user explicitly asked to save the workflow as a shared skill
2. The skill body captures the multi-step recipe so future agents can follow it
3. A specific kebab-case name and a description with "when to use it" wording make it discoverable
""".strip()

POSITIVE_EXAMPLE_UPDATE_SKILL = """
User: The audit-error-tracking skill is missing the step where we group by impact
Assistant: I'll fetch the skill, then publish a targeted edit.
*Uses get_llm_skill with skill_name: "audit-error-tracking" to read the body and note the current version*
*Uses update_llm_skill with skill_name: "audit-error-tracking", base_version: <fetched version>, and edits that insert the new step*
""".strip()

POSITIVE_EXAMPLE_UPDATE_SKILL_REASONING = """
The assistant used get_llm_skill then update_llm_skill because:
1. Updates need the current version for optimistic concurrency — fetch first
2. The change is a small insertion, so `edits` is more precise (and less risky) than rewriting the whole body
3. Carrying every other field forward means the assistant didn't have to round-trip description, license, files, etc.
""".strip()

AI_OBSERVABILITY_MODE_DESCRIPTION = "Specialized mode for AI observability. Search and analyze LLM traces for usage, costs, latency, and errors. Write and test Hog evaluation code against real events. Create, update, and archive shared agent skills for the team."


class AIObservabilityAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SEARCH_TRACES,
            reasoning=POSITIVE_EXAMPLE_SEARCH_TRACES_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE,
            reasoning=POSITIVE_EXAMPLE_INVESTIGATE_EXPENSIVE_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL,
            reasoning=POSITIVE_EXAMPLE_WRITE_AND_TEST_EVAL_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_FIX_EVAL_ERRORS,
            reasoning=POSITIVE_EXAMPLE_FIX_EVAL_ERRORS_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_DISCOVER_SKILL,
            reasoning=POSITIVE_EXAMPLE_DISCOVER_SKILL_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SAVE_SKILL,
            reasoning=POSITIVE_EXAMPLE_SAVE_SKILL_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_UPDATE_SKILL,
            reasoning=POSITIVE_EXAMPLE_UPDATE_SKILL_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.ai_observability.backend.tools.run_hog_eval import RunHogEvalTestTool
        from products.skills.backend.tools.skills import ArchiveLLMSkillTool, CreateLLMSkillTool, UpdateLLMSkillTool

        return [
            SearchLLMTracesTool,
            RunHogEvalTestTool,
            CreateLLMSkillTool,
            UpdateLLMSkillTool,
            ArchiveLLMSkillTool,
        ]


ai_observability_agent = AgentModeDefinition(
    mode=AgentMode.LLM_ANALYTICS,
    mode_description=AI_OBSERVABILITY_MODE_DESCRIPTION,
    toolkit_class=AIObservabilityAgentToolkit,
)


chat_agent_plan_ai_observability_agent = AgentModeDefinition(
    mode=AgentMode.LLM_ANALYTICS,
    mode_description=AI_OBSERVABILITY_MODE_DESCRIPTION,
    toolkit_class=AIObservabilityAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
