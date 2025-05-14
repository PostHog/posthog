import json
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Literal, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT
from ee.hogai.utils.types import AssistantState
from posthog.schema import AssistantContextualTool

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

MaxSupportedQueryKind = Literal["trends", "funnel", "retention", "sql"]


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Retrieve results for a specific data question by creating a query or iterate on a previous query.
    This tool only retrieves data for a single insight at a time.
    The `trends` insight type is the only insight that can display multiple trends insights in one request.
    All other insight types strictly return data for a single insight.
    This tool is also relevant if the user asks to write SQL.
    """

    query_description: str = Field(
        description="The description of the query being asked. Include all relevant details from the current conversation in the query description, as the tool cannot access the conversation history."
    )
    query_kind: MaxSupportedQueryKind = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


class search_documentation(BaseModel):
    """
    Search PostHog documentation to answer questions about features, concepts, and usage.
    Use this tool when the user asks about how to use PostHog, its features, or needs help understanding concepts.
    Don't use this tool if the necessary information is already in the conversation.
    """


CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantContextualTool, type["MaxTool"]] = {}


class MaxTool(BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    thinking_message: str
    """The message shown to let the user know this tool is being used. One sentence, no punctuation.
    For example, "Updating filters"
    """
    root_system_prompt_template: str = "No context provided for this tool."
    """The template for context associated with this tool, that will be injected into the root node's system prompt.
    Use this if you need to strongly steer the root node in decideing _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    _context: dict[str, Any]
    _team: Optional["Team"]
    _user: Optional["User"]
    _config: RunnableConfig
    _state: AssistantState

    @abstractmethod
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        pass

    def __init__(self, state: AssistantState | None = None):
        super().__init__()
        self._state = state if state else AssistantState(messages=[])

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.endswith("Tool"):
            raise ValueError("The name of a MaxTool subclass must end with 'Tool', for clarity")
        try:
            accepted_name = AssistantContextualTool(cls.name)
        except ValueError:
            raise ValueError(
                f"MaxTool name '{cls.name}' is not a recognized AssistantContextualTool value. Fix this name, or update AssistantContextualTool in schema-assistant-messages.ts and run `pnpm schema:build`"
            )
        CONTEXTUAL_TOOL_NAME_TO_TOOL[accepted_name] = cls
        if not getattr(cls, "thinking_message", None):
            raise ValueError("You must set `thinking_message` on the tool, so that we can show the tool kicking off")

    def _run(self, *args, config: RunnableConfig, **kwargs):
        self._context = config["configurable"].get("contextual_tools", {}).get(self.get_name(), {})
        self._team = config["configurable"]["team"]
        self._user = config["configurable"]["user"]
        self._config = {
            "recursion_limit": 48,
            "callbacks": config.get("callbacks", []),
            "configurable": {
                "thread_id": config["configurable"].get("thread_id"),
                "trace_id": config["configurable"].get("trace_id"),
                "distinct_id": config["configurable"].get("distinct_id"),
                "team": self._team,
                "user": self._user,
            },
        }
        return self._run_impl(*args, **kwargs)

    @property
    def context(self) -> dict:
        if not hasattr(self, "_context"):
            raise AttributeError("Tool has not been run yet")
        return self._context

    def format_system_prompt_injection(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.root_system_prompt_template.format(**formatted_context)


# Define the exact possible page keys for navigation. Extracted using the following Cursor prompt:
# "
# List every key of the `frontend/src/products.tsx::productUrls` object,
# whose function takes either zero arguments, or only one optional argument named `tab` (exactly `tab`).
# Your only output should be a list of those string keysin Python `Literal[..., ..., ...]` syntax.
# Once done, verify whether indeed each item of the output satisfies the argument criterion.
# "
PageKeyLiterals = Literal[
    "createAction",
    "actions",
    "cohorts",
    "dashboards",
    "earlyAccessFeatures",
    "errorTracking",
    "errorTrackingConfiguration",
    "experiments",
    "experimentsSharedMetrics",
    "featureFlags",
    "game368hedgehogs",
    "links",
    "llmObservabilityDashboard",
    "llmObservabilityGenerations",
    "llmObservabilityTraces",
    "llmObservabilityUsers",
    "llmObservabilityPlayground",
    "logs",
    "managedMigration",
    "managedMigrationNew",
    "messaging",
    "messagingCampaignNew",
    "messagingLibraryTemplateNew",
    "notebooks",
    "canvas",
    "persons",
    "insights",
    "savedInsights",
    "alerts",
    "replayFilePlayback",
    "revenueAnalytics",
    "surveys",
    "surveyTemplates",
    "userInterviews",
    "webAnalytics",
    "webAnalyticsWebVitals",
    "webAnalyticsPageReports",
    "webAnalyticsMarketing",
]


class NavigateToolArgs(BaseModel):
    page_key: PageKeyLiterals = Field(
        description="The specific key identifying the page to navigate to. Must be one of the predefined literal values."
    )


PAGE_TOOL_MAP: dict[PageKeyLiterals, list[str]] = {
    "insightNew": ["create_and_query_insight"],
    "sqlEditor": ["generate_hogql_query"],
    "replay": ["search_session_recordings"],
}


class NavigateTool(MaxTool):
    name: str = "navigate"
    description: str = (
        "Navigates to a specified, predefined page or section within the PostHog application using a specific page key. "
        "Use this for known destinations like 'insights', 'replay', 'feature flags', 'project settings', 'organization settings', 'dashboards list', 'actions', 'notebooks', etc. "
        "This tool uses a fixed list of page keys and cannot navigate to arbitrary URLs or pages requiring dynamic IDs not already encoded in the page key. "
        "After navigating, you'll be able to use that page's tools."
    )
    root_system_prompt_template: str = (
        "You're currently on the {current_page} page. "
        "You can navigate to one of the available pages using the 'navigate' tool. "
        "Some of these pages have tools that you can use to get more information or perform actions. "
        f"Here's a mapping of pages to tools available:\n"
        "\n".join([f"- {page}: {', '.join(PAGE_TOOL_MAP[page])}" for page in PAGE_TOOL_MAP])
    )
    thinking_message: str = "Navigating"
    args_schema: type[BaseModel] = NavigateToolArgs

    def _run_impl(self, page_key: PageKeyLiterals) -> tuple[str, Any]:
        return f"Navigated to `{page_key}`.", {"page_key": page_key}
