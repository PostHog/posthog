import json
import pkgutil
import importlib
from typing import Any, Literal

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from posthog.schema import AssistantContextualTool, AssistantNavigateUrl

from posthog.models import Team, User

import products

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import InsightQuery


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Retrieve results for a specific data question by creating a query (aka insight), or iterate on a previous query.
    This tool only retrieves data for a single query at a time.
    """

    query_description: str = Field(
        description=(
            "A description of the query to generate, encapsulating the details of the user's request. "
            "Include all relevant context from earlier messages too, as the tool won't see that conversation history. "
            "If an existing insight has been used as a starting point, include that insight's filters and query in the description. "
            "Don't be overly prescriptive with event or property names, unless the user indicated they mean this specific name (e.g. with quotes). "
            "If the users seems to ask for a list of entities, rather than a count, state this explicitly. "
            "Explicitly include the time range, time grain, metric/aggregation, events/steps, and breakdown/filters provided by the user; if any are missing, choose sensible defaults and state them."
        )
    )


class search_insights(BaseModel):
    """
    Search through existing insights to find matches based on the user's query.

    WHEN TO USE THIS TOOL:
    - The user explicitly asks to find/search/look up existing insights
    - The request is ambiguous or exploratory and likely to be satisfied by reusing a saved insight

    WHEN NOT TO USE THIS TOOL:
    - The user gives a specific, actionable analysis request (metric/aggregation, events, filters, and/or a time range)
    - The user asks to create a dashboard (use `create_dashboard` instead)

    If the request has enough information to generate an insight, use `create_and_query_insight` directly.
    """

    search_query: str = Field(
        description="The user's query to search for insights. "
        "Include all relevant context from earlier messages too, as the tool won't see that conversation history."
    )


class session_summarization(BaseModel):
    """
    - Summarize session recordings to find patterns and issues by summarizing sessions' events.
    - When to use the tool:
      * When the user asks to summarize session recordings
        - "summarize" synonyms: "watch", "analyze", "review", and similar
        - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar
    - When NOT to use the tool:
      * When the user asks to find, search for, or look up session recordings, but doesn't ask to summarize them
      * When users asks to update, change, or adjust session recordings filters
    """

    session_summarization_query: str = Field(
        description="""
        - The user's complete query for session recordings summarization.
        - This will be used to find relevant session recordings.
        - Always pass the user's complete, unmodified query.
        - Examples:
          * 'summarize all session recordings from yesterday'
          * 'analyze mobile user session recordings from last week, even if 1 second'
          * 'watch last 300 session recordings of MacOS users from US'
          * and similar
        """
    )
    should_use_current_filters: bool = Field(
        description="""
        - Whether to use current filters from user's UI to find relevant session recordings.
        - IMPORTANT: Should be always `false` if the current filters or `search_session_recordings` tool are not present in the conversation history.
        - Examples:
          * Set to `true` if one of the conditions is met:
            - the user wants to summarize "current/selected/opened/my/all/these" session recordings
            - the user wants to use "current/these" filters
            - the user's query specifies filters identical to the current filters
            - if the user's query doesn't specify any filters/conditions
            - the user refers to what they're "looking at" or "viewing"
          * Set to `false` if one of the conditions is met:
            - no current filters or `search_session_recordings` tool are present in the conversation
            - the user specifies date/time period different from the current filters
            - the user specifies conditions (user, device, id, URL, etc.) not present in the current filters
        """,
    )
    summary_title: str = Field(
        description="""
        - The name of the summary that is expected to be generated from the user's `session_summarization_query` and/or `current_filters` (if present).
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
          * If `should_use_current_filters` is `false`, then the `summary_title` should be generated based on the `session_summarization_query`:
            - query: "I want to watch all the sessions of user `user@example.com` in the last 30 days no matter how long" -> name: "Sessions of the user user@example.com (last 30 days)"
            - query: "summarize my last 100 session recordings" -> name: "Last 100 sessions"
            - and similar
          * If `should_use_current_filters` is `true`, then the `summary_title` should be generated based on the current filters in the context (if present):
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
          * If there's not enough context to generated the summary name - keep it an empty string ("")
        """
    )


class create_dashboard(BaseModel):
    """
    Create a dashboard with insights based on the user's request.
    Use this tool when users ask to create, build, or make a new dashboard with insights.
    This tool will search for existing insights that match the user's requirements so no need to call `search_insights` tool.
    or create new insights if none are found, then combine them into a dashboard.
    Do not call this tool if the user only asks to find, search for, or look up existing insights and does not ask to create a dashboard.
    If you decided to use this tool, there is no need to call `search_insights` tool beforehand. The tool will search for existing insights that match the user's requirements and create new insights if none are found.
    """

    search_insights_queries: list[InsightQuery] = Field(
        description="A list of insights to be included in the dashboard. Include all the insights that the user mentioned."
    )
    dashboard_name: str = Field(
        description=(
            "The name of the dashboard to be created based on the user request. It should be short and concise as it will be displayed as a header in the dashboard tile."
        )
    )


class search_documentation(BaseModel):
    """
    Answer the question using the latest PostHog documentation. This performs a documentation search.
    PostHog docs and tutorials change frequently, which makes this tool required.
    Do NOT use this tool if the necessary information is already in the conversation or context (except when you need to check whether an assumption presented is correct or not).
    """


class retrieve_billing_information(BaseModel):
    """
    Retrieve detailed billing information for the current organization.
    Use this tool when the user asks about billing, subscription, usage, or spending related questions.
    """


CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantContextualTool, type["MaxTool"]] = {}


def _import_max_tools() -> None:
    """TRICKY: Dynamically import max_tools from all products"""
    for module_info in pkgutil.iter_modules(products.__path__):
        if module_info.name in ("conftest", "test"):
            continue  # We mustn't import test modules in prod
        try:
            importlib.import_module(f"products.{module_info.name}.backend.max_tools")
        except ModuleNotFoundError:
            pass  # Skip if backend or max_tools doesn't exist - note that the product's dir needs a top-level __init__.py


def get_contextual_tool_class(tool_name: str) -> type["MaxTool"] | None:
    """Get the tool class for a given tool name, handling circular import."""
    _import_max_tools()  # Ensure max_tools are imported
    from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL

    return CONTEXTUAL_TOOL_NAME_TO_TOOL[AssistantContextualTool(tool_name)]


class MaxTool(AssistantContextMixin, BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    thinking_message: str
    """The message shown to let the user know this tool is being used. One sentence, no punctuation.
    For example, "Updating filters"
    """

    root_system_prompt_template: str = "No context provided for this tool."
    """The template for context associated with this tool, that will be injected into the root node's system prompt.
    Use this if you need to strongly steer the root node in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    show_tool_call_message: bool = Field(description="Whether to show tool call messages.", default=True)

    _context: dict[str, Any]
    _config: RunnableConfig
    _state: AssistantState

    # DEPRECATED: Use `_arun_impl` instead
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """DEPRECATED. Use `_arun_impl` instead."""
        raise NotImplementedError

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        raise NotImplementedError

    def __init__(self, *, team: Team, user: User, state: AssistantState | None = None, **kwargs):
        super().__init__(**kwargs)
        self._team = team
        self._user = user
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
        self._init_run(config)
        try:
            return self._run_impl(*args, **kwargs)
        except NotImplementedError:
            pass
        return async_to_sync(self._arun_impl)(*args, **kwargs)

    async def _arun(self, *args, config: RunnableConfig, **kwargs):
        self._init_run(config)
        try:
            return await self._arun_impl(*args, **kwargs)
        except NotImplementedError:
            pass
        return await super()._arun(*args, config=config, **kwargs)

    def _init_run(self, config: RunnableConfig):
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


class NavigateToolArgs(BaseModel):
    page_key: AssistantNavigateUrl = Field(
        description="The specific key identifying the page to navigate to. Must be one of the predefined literal values."
    )


class NavigateTool(MaxTool):
    name: str = "navigate"
    description: str = (
        "Navigates to a specified, predefined page or section within the PostHog application using a specific page key. "
        "This tool uses a fixed list of page keys and cannot navigate to arbitrary URLs or pages requiring dynamic IDs not already encoded in the page key. "
        "After navigating, you'll be able to use that page's tools."
    )
    root_system_prompt_template: str = (
        "You're currently on the {current_page} page. "
        "You can navigate around the PostHog app using the 'navigate' tool.\n\n"
        "Some of the pages in the app have helpful descriptions. Some have tools that you can use only there. See the following list:\n"
        "{scene_descriptions}\n"
        "After navigating to a new page, you'll have access to that page's specific tools."
    )
    thinking_message: str = "Navigating"
    args_schema: type[BaseModel] = NavigateToolArgs

    def _run_impl(self, page_key: AssistantNavigateUrl) -> tuple[str, Any]:
        # Note that page_key should get replaced by a nicer breadcrumbs-based name in the frontend
        # but it's useful for the LLM to still have the page_key in chat history
        return f"Navigated to **{page_key}**.", {"page_key": page_key}
