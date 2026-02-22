from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.chat_agent.executables import (
    ChatAgentExecutable,
    ChatAgentPlanExecutable,
    ChatAgentPlanToolsExecutable,
    ChatAgentToolsExecutable,
)
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_WRITE_AND_TEST = """
User: Write a Hog eval that checks if the output is longer than 10 characters
Assistant: I'll write a Hog evaluation and test it against your recent events.
*Uses run_hog_eval_test with source: 'let result := length(output) > 10; print(concat("Output length: ", toString(length(output)))); return result;'*
""".strip()

POSITIVE_EXAMPLE_WRITE_AND_TEST_REASONING = """
The assistant used run_hog_eval_test because:
1. The user wants to create a Hog evaluation that checks output length
2. The tool compiles and runs the code against real events to verify it works
3. The results show whether the evaluation logic is correct
""".strip()

POSITIVE_EXAMPLE_FIX_ERRORS = """
User: The eval is failing with a null error on some events
Assistant: I'll fix the null handling and test again.
*Uses run_hog_eval_test with updated source that adds null checks*
After seeing the results, the assistant explains what was fixed.
""".strip()

POSITIVE_EXAMPLE_FIX_ERRORS_REASONING = """
The assistant used run_hog_eval_test because:
1. The user reported errors in the evaluation code
2. Testing with the tool reveals which events cause null errors
3. The assistant can iterate on the fix by running the tool again
""".strip()


class EvaluationsAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_WRITE_AND_TEST,
            reasoning=POSITIVE_EXAMPLE_WRITE_AND_TEST_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_FIX_ERRORS,
            reasoning=POSITIVE_EXAMPLE_FIX_ERRORS_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.llm_analytics.backend.tools.run_hog_eval_test import RunHogEvalTestTool

        return [RunHogEvalTestTool]


MODE_DESCRIPTION = "Specialized mode for writing and testing Hog evaluation code for LLM analytics. This mode allows you to compile Hog code, run it against real events, see pass/fail/error results, and iterate on fixes."

evaluations_agent = AgentModeDefinition(
    mode=AgentMode.EVALUATIONS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=EvaluationsAgentToolkit,
    node_class=ChatAgentExecutable,
    tools_node_class=ChatAgentToolsExecutable,
)

chat_agent_plan_evaluations_agent = AgentModeDefinition(
    mode=AgentMode.EVALUATIONS,
    mode_description=MODE_DESCRIPTION,
    toolkit_class=EvaluationsAgentToolkit,
    node_class=ChatAgentPlanExecutable,
    tools_node_class=ChatAgentPlanToolsExecutable,
)
