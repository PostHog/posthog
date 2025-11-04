from typing import Any

import django.utils.timezone

from asgiref.sync import async_to_sync
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import SurveyCreationSchema

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, Survey, Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool

SURVEY_CREATION_SYSTEM_PROMPT = """You are an expert survey designer helping users create PostHog in-app surveys through natural language instructions.

## Your Role
Transform user requests into well-structured, concise survey configurations that follow PostHog in-app survey best practices.

## CRITICAL: In-App Survey Design Principles
**These are in-app surveys that appear as overlays while users are actively using the product.**
- **Keep surveys SHORT**: 1-3 questions preferred, unless explicitly requested otherwise
- **Be respectful of user time**: Users are trying to accomplish tasks, not fill out surveys
- **Focus on ONE key insight**: Don't try to gather everything at once
- **Prioritize user experience**: A short survey with high completion rates is better than a long abandoned survey

## Survey Types Available
- **popover**: Small overlay that appears on the page (most common for in-app surveys)
- **widget**: A widget that appears on the page, either via a CSS selector or automatic using a embedded button
- **api**: Headless survey for custom implementations

## Targeting & Display Conditions
Convert natural language targeting into proper conditions:
- **URL-based**: "users on pricing page" → url_matching with "/pricing" pattern
- **Device**: "mobile users" → device type conditions
- **User segments**: "returning users" → user property filters
- **Time-based**: "after 30 seconds" → wait_period conditions
- **Page elements**: "users who clicked signup" → CSS selector conditions
- **Feature flag-based**: "users with feature flag X enabled" → linked_flag_id with existing feature flag
- **Feature flag variant-based**: "users in variant Y of feature flag X" → linked_flag_id + linkedFlagVariant in conditions

### Common Targeting Patterns
- "users on [page]" → `{"url_matching": [{"text": "[page]", "match_type": "contains"}]}`
- "mobile users" → `{"device_type": "Mobile"}`
- "new users" → user property targeting
- "after [X] seconds" → `{"wait_period": X}`
- "users with [feature flag] enabled" → `{"linked_flag_id": [flag_id]}`
- "users in [variant] variant of [feature flag]" → `{"linked_flag_id": [flag_id], "conditions": {"linkedFlagVariant": "[variant]"}}`

## Question Types You Can Create
1. **open**: Free-form text input
   - Use for: Feedback, suggestions, detailed responses
   - Example: "What could we improve about our dashboard?"

2. **single_choice**: Select one option from multiple choices
   - Use for: Yes/No, satisfaction levels, categorical choices
   - Example: "How satisfied are you?" with choices ["Very satisfied", "Satisfied", "Neutral", "Dissatisfied", "Very dissatisfied"]

3. **multiple_choice**: Select multiple options
   - Use for: Feature preferences, multi-faceted feedback
   - Example: "Which features do you use most?" with multiple selectable options

4. **rating**: Numeric or emoji scale
   - Use for: NPS, CSAT, ease ratings
   - Scales: 5, 7, 10 (number) or 5 (emoji)
   - Example: "How likely are you to recommend us?" (1-10 scale for NPS)
   - NPS Surveys should always use a scale value of 10.

5. **link**: Display a link with call-to-action
   - Use for: Directing users to external resources
   - Example: "Learn more about our new feature" with link to docs

## Survey Intent Recognition
- **NPS (Net Promoter Score)**: "How likely are you to recommend..." (rating 1-10)
- **CSAT (Customer Satisfaction)**: "How satisfied are you..." (rating 1-5)
- **PMF (Product Market Fit)**: "How would you feel if you could no longer use..." (single choice)
- **Feedback**: General open-ended questions about experience
- **Research**: Multiple questions to understand user behavior

## Context Utilization
Use the provided context to make intelligent decisions:

**Team Configuration (Default Settings)**:
The following team configuration will be applied as defaults:
{{{team_survey_config}}}
- Apply team's default appearance settings (colors, branding)
- Use configured thank you messages and display preferences
- Respect team's survey frequency limits

**Existing Surveys**:
{{{existing_surveys}}}
- Avoid creating duplicate surveys with similar purposes
- Reference existing survey names for consistency
- Suggest complementary surveys if user has NPS but lacks CSAT
- Check for survey fatigue (too many active surveys on same pages)

## Feature Flag Key Lookup Usage
When users reference feature flags by name (e.g., "new-onboarding-flow", "beta-dashboard"), you must:
1. **Use the lookup_feature_flag tool** to get the feature flag ID and available variants
2. **Convert flag keys to IDs** before creating surveys - the API requires `linked_flag_id` (integer), not flag keys
3. **Validate variants** - ensure any specified variant exists, or use "any" for any variant
4. **Multiple variants support** - if multiple variants are given, use "any" instead
5. **Handle missing flags** - if a flag doesn't exist, inform the user and suggest alternatives

**Example workflow**:
- User says: "Survey users with the new-dashboard flag enabled"
- You call: `lookup_feature_flag("new-dashboard")`
- You use the returned ID in: `{"linked_flag_id": 123}`
- If user specifies variant: `{"linked_flag_id": 123, "conditions": {"linkedFlagVariant": "treatment"}}`

## Guidelines
1. **KEEP IT SHORT**: 1-3 questions maximum - this is non-negotiable for in-app surveys
2. **ONE PRIMARY QUESTION**: Focus on the most important insight you need
3. **Clear question text**: Use simple, unambiguous language
4. **Logical flow**: If multiple questions, order from general to specific
5. **Smart defaults**: Use "popover" type and team appearance settings unless specified
6. **Appropriate scales**: NPS uses 1-10, CSAT uses 1-5, PMF uses specific choices
7. **Required vs Optional**: First question should typically be required, follow-ups can be optional
8. **Respect user context**: Remember users are in the middle of using the product

## Common Patterns to Follow
- **NPS**: "How likely are you to recommend [product] to a friend or colleague?" (1-10 scale)
- **CSAT**: "How satisfied are you with [experience]?" (1-5 scale)
- **PMF**: "How would you feel if you could no longer use [product]?" (Very disappointed/Somewhat disappointed/Not disappointed)
- **Feedback**: "What could we improve about [feature]?" (open text, optional)

## Multi-Question Survey Patterns (Use Sparingly)
For complex surveys, follow these patterns but keep total questions to 2-3:
- **NPS + Follow-up**: NPS rating → "What could we improve?" (open, optional)
- **CSAT + Details**: Satisfaction rating → Specific feedback (open, optional)
- **Feature Research**: Usage questions → Improvement suggestions → Priority ranking

## Examples
**Simple NPS**: "Create an NPS survey"
**Targeted Feedback**: "Get feedback on the dashboard from mobile users"
**Complex Research**: "Survey users about our pricing page experience"
**Feature Flag Targeting**: "Survey users who have the 'new-dashboard' feature flag enabled"
**Multi-Variant Testing**: "Get feedback from users seeing the 'new-dashboard' feature flag and 'new-design' variant of our homepage"

**Important**: When users mention feature flag names, always use the lookup_feature_flag tool first to get the actual flag ID and available variants. After getting the lookup results and having generated the survey, immediately use the final_answer tool to provide the complete information.

## Critical Rules
- DO NOT LAUNCH SURVEYS unless user explicitly asks to launch them
- Always validate JSON structure before responding
- Use team appearance settings when available
- Consider survey fatigue - don't oversaturate users
- Prioritize user experience over data collection
""".strip()


class FeatureFlagLookupGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Graph for feature flag lookup operations."""

    def __init__(self, team: Team, user: User, tool_call_id: str):
        super().__init__(
            team,
            user,
            tool_call_id,
            loop_node_class=SurveyLoopNode,
            tools_node_class=SurveyLookupToolsNode,
            toolkit_class=SurveyToolkit,
        )


class SurveyCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the survey to create")


def get_team_survey_config(team: Team) -> dict[str, Any]:
    """Get team survey configuration for context."""
    survey_config = getattr(team, "survey_config", {}) or {}
    return {
        "appearance": survey_config.get("appearance", {}),
        "default_settings": {"type": "popover", "enable_partial_responses": True},
    }


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = "Create and optionally launch a survey based on natural language instructions"

    args_schema: type[BaseModel] = SurveyCreatorArgs

    async def _create_survey_from_instructions(self, instructions: str) -> SurveyCreationSchema:
        """
        Create a survey from natural language instructions.
        """
        # Import here to avoid circular dependency at module load time

        graph = FeatureFlagLookupGraph(team=self._team, user=self._user, tool_call_id=self._tool_call_id)

        graph_context = {
            "change": f"Create a survey based on these instructions: {instructions}",
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context)

        if isinstance(result["output"], SurveyCreationSchema):
            return result["output"]
        else:
            survey_creation_schema = SurveyCreationSchema(
                questions=[], should_launch=False, name="", description="", type="popover"
            )
            capture_exception(
                Exception(f"Survey creation graph returned unexpected output type: {type(result.get('output'))}"),
                {"team_id": self._team.id, "user_id": self._user.id, "result": str(result)},
            )
            return survey_creation_schema

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """
        Generate survey configuration from natural language instructions.
        """
        try:
            user = self._user
            team = self._team

            result = await self._create_survey_from_instructions(instructions)

            try:
                if not result.questions:
                    return "❌ Survey must have at least one question", {
                        "error": "validation_failed",
                        "error_message": "No questions were created from the survey instructions.",
                    }

                # Apply appearance defaults and prepare survey data
                survey_data = self._prepare_survey_data(result, team)

                # Set launch date if requested
                if result.should_launch:
                    survey_data["start_date"] = django.utils.timezone.now()

                # Create the survey directly using Django ORM
                survey = await Survey.objects.acreate(team=team, created_by=user, **survey_data)

                launch_msg = " and launched" if result.should_launch else ""
                return f"✅ Survey '{survey.name}' created{launch_msg} successfully!", {
                    "survey_id": survey.id,
                    "survey_name": survey.name,
                }

            except Exception as validation_error:
                return f"❌ Survey validation failed: {str(validation_error)}", {
                    "error": "validation_failed",
                    "error_message": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "❌ Failed to create survey", {"error": "creation_failed", "details": str(e)}

    def _prepare_survey_data(self, survey_schema: SurveyCreationSchema, team: Team) -> dict[str, Any]:
        """Prepare survey data with appearance defaults applied."""
        # Convert schema to dict, removing should_launch field
        if hasattr(survey_schema, "model_dump"):
            survey_data = survey_schema.model_dump(exclude_unset=True, exclude={"should_launch"})
        else:
            survey_data = survey_schema.__dict__.copy()
            survey_data.pop("should_launch", None)

        # Ensure required fields have defaults
        survey_data.setdefault("archived", False)
        survey_data.setdefault("description", "")
        survey_data.setdefault("enable_partial_responses", True)

        # Apply appearance defaults
        appearance = DEFAULT_SURVEY_APPEARANCE.copy()

        # Override with team-specific defaults if they exist
        team_appearance = get_team_survey_config(team).get("appearance", {})
        if team_appearance:
            appearance.update(team_appearance)

        # Finally, override with survey-specified appearance settings
        if survey_data.get("appearance"):
            survey_appearance = survey_data["appearance"]
            # Convert to dict if needed
            if hasattr(survey_appearance, "model_dump"):
                survey_appearance = survey_appearance.model_dump(exclude_unset=True)
            elif hasattr(survey_appearance, "__dict__"):
                survey_appearance = survey_appearance.__dict__
            # Only update fields that are actually set (not None)
            appearance.update({k: v for k, v in survey_appearance.items() if v is not None})

        # Always set appearance to ensure surveys have consistent defaults
        survey_data["appearance"] = appearance

        return survey_data


class SurveyToolkit(TaxonomyAgentToolkit):
    """Toolkit for survey creation and feature flag lookup operations."""

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    def get_tools(self) -> list:
        """Get all tools (default + custom). Override in subclasses to add custom tools."""
        return self._get_custom_tools()

    def _get_custom_tools(self) -> list:
        """Get custom tools for feature flag lookup."""

        class lookup_feature_flag(BaseModel):
            """
            Use this tool to lookup a feature flag by its key/name to get detailed information including ID and variants.
            Returns a message with the flag ID and the variants if the flag is found and the variants are available.
            """

            flag_key: str = Field(description="The key/name of the feature flag to look up")

        class final_answer(base_final_answer[SurveyCreationSchema]):
            __doc__ = base_final_answer.__doc__

        return [lookup_feature_flag, final_answer, ask_user_for_help]

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        """Handle custom tool execution."""
        results = {}
        unhandled_tools = {}
        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "lookup_feature_flag":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._lookup_feature_flag(tool_input.arguments.flag_key)  # type: ignore
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    @database_sync_to_async(thread_sensitive=False)
    def _lookup_feature_flag(self, flag_key: str) -> str:
        """Look up feature flag information by key."""
        try:
            # Look up the feature flag by key for the current team
            feature_flag = FeatureFlag.objects.get(key=flag_key, team_id=self._team.id)

            # Get available variants
            variants = [variant["key"] for variant in feature_flag.variants]

            message = f"Found feature flag '{flag_key}' (ID: {feature_flag.id})"
            if variants:
                message += f" with variants: {', '.join(variants)}"
            else:
                message += " (no variants)"

            return message

        except FeatureFlag.DoesNotExist:
            return f"Feature flag '{flag_key}' not found in the team's feature flags."
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id})
            return f"Error looking up feature flag: '{flag_key}'"


class SurveyLoopNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Node for feature flag lookup operations."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SurveyToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    async def _get_existing_surveys_summary(self) -> str:
        """Get summary of existing surveys for context."""
        try:
            surveys = [survey async for survey in Survey.objects.filter(team_id=self._team.id, archived=False)[:5]]

            if not surveys:
                return "No existing surveys"

            summaries = []
            for survey in surveys:
                status = "active" if survey.start_date and not survey.end_date else "draft"
                summaries.append(f"- '{survey.name}' ({survey.type}, {status})")

            return "\n".join(summaries)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "Unable to load existing surveys"

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get system prompts for feature flag lookup."""
        existing_surveys = async_to_sync(self._get_existing_surveys_summary)()

        prompt = ChatPromptTemplate([("system", SURVEY_CREATION_SYSTEM_PROMPT)], template_format="mustache").format(
            existing_surveys=existing_surveys,
            team_survey_config=get_team_survey_config(self._team),
        )

        return ChatPromptTemplate([("system", prompt)], template_format="mustache")

    def _construct_messages(self, state: TaxonomyAgentState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        system_prompt = self._get_system_prompt()
        conversation = list(system_prompt.messages)
        human_content = state.change or ""
        all_messages = [*conversation, ("human", human_content)]

        progress_messages = state.tool_progress_messages or []
        all_messages.extend(progress_messages)

        return ChatPromptTemplate(all_messages, template_format="mustache")


class SurveyLookupToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Tools node for feature flag lookup operations."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SurveyToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)
