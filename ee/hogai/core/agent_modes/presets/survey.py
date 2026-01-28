from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tools.todo_write import TodoWriteExample

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


POSITIVE_EXAMPLE_CREATE_SURVEY = """
User: Create an NPS survey for my pricing page
Assistant: I'll create an NPS survey that appears on your pricing page.
*Uses create_survey with instructions: "Create an NPS survey that appears on the pricing page"*
""".strip()

POSITIVE_EXAMPLE_CREATE_SURVEY_REASONING = """
The assistant used the create_survey tool because:
1. The user wants to create a new survey with clear requirements
2. The survey type (NPS) and targeting (pricing page) are specified
3. This is a straightforward survey creation that doesn't require multiple steps
""".strip()

POSITIVE_EXAMPLE_ANALYZE_SURVEY = """
User: What are users saying in the feedback survey?
Assistant: I'll retrieve the survey responses and analyze them for you.
*Uses analyze_survey_responses to get the response data*
Based on the 47 responses, here are the key themes I identified:
1. **Performance concerns** - Users mention slow loading times (12 responses)
2. **Feature requests** - Dark mode and mobile improvements requested (8 responses)
3. **Positive feedback** - Users appreciate the intuitive interface (15 responses)
Overall sentiment is mixed, with actionable recommendations to prioritize performance optimization.
""".strip()

POSITIVE_EXAMPLE_ANALYZE_SURVEY_REASONING = """
The assistant used the analyze_survey_responses tool because:
1. The user wants to understand feedback from survey responses
2. The tool retrieves the open-ended responses from the survey
3. The assistant then analyzes the responses to identify themes, sentiment, and actionable insights
""".strip()

POSITIVE_EXAMPLE_SURVEY_WITH_FLAG = """
User: Create a survey for users who have the new-checkout feature flag enabled
Assistant: I'll first search for the feature flag to get its ID, then create the survey targeting those users.
*Creates todo list with the following items:*
1. Search for the new-checkout feature flag to get its ID
2. Create a survey targeting users with that flag enabled
*Uses search with kind: "feature_flags" and query: "new-checkout"*
After getting the flag ID, the assistant uses create_survey with the flag targeting.
""".strip()

POSITIVE_EXAMPLE_SURVEY_WITH_FLAG_REASONING = """
The assistant used the todo list because:
1. The user wants to target a survey based on a feature flag
2. This requires multiple steps: first find the flag ID, then create the survey
3. The search tool with feature_flags kind retrieves the flag information
4. Breaking this into steps ensures the assistant gets the flag ID before creating the survey
""".strip()

POSITIVE_EXAMPLE_EDIT_SURVEY = """
User: Stop the NPS survey and archive it
Assistant: I'll first search for the NPS survey, then stop and archive it.
*Creates todo list with the following items:*
1. Search for the NPS survey to get its ID
2. Stop and archive the survey
*Uses search with kind: "surveys" and query: "NPS"*
After getting the survey ID, the assistant uses edit_survey with survey_id and updates: {end_date: "now", archived: true}
""".strip()

POSITIVE_EXAMPLE_EDIT_SURVEY_REASONING = """
The assistant used the todo list because:
1. The user wants to modify an existing survey (stop and archive)
2. This requires multiple steps: first find the survey ID, then apply the updates
3. The search tool with surveys kind retrieves the survey information
4. The edit_survey tool is used with end_date="now" to stop and archived=true to archive
""".strip()


class SurveyAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_CREATE_SURVEY,
            reasoning=POSITIVE_EXAMPLE_CREATE_SURVEY_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_ANALYZE_SURVEY,
            reasoning=POSITIVE_EXAMPLE_ANALYZE_SURVEY_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SURVEY_WITH_FLAG,
            reasoning=POSITIVE_EXAMPLE_SURVEY_WITH_FLAG_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_EDIT_SURVEY,
            reasoning=POSITIVE_EXAMPLE_EDIT_SURVEY_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        from products.surveys.backend.max_tools import CreateSurveyTool, EditSurveyTool, SurveyAnalysisTool

        tools: list[type[MaxTool]] = [CreateSurveyTool, EditSurveyTool, SurveyAnalysisTool]
        return tools


survey_agent = AgentModeDefinition(
    mode=AgentMode.SURVEY,
    mode_description="Specialized mode for creating and analyzing surveys. Create surveys with natural language including targeting by URL, user properties, and feature flags. Analyze survey responses to extract themes, sentiment, and actionable insights.",
    toolkit_class=SurveyAgentToolkit,
)
