import importlib
import json
import pkgutil
from typing import TYPE_CHECKING, Any, Literal, Optional

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

import products
from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT
from ee.hogai.utils.types import AssistantState
from posthog.schema import AssistantContextualTool, AssistantNavigateUrls

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


class search_insights(BaseModel):
    """
    Search through existing insights to find matches based on the user's query.
    Use this tool when users ask to find, search for, or look up existing insights.
    """

    search_query: str = Field(
        description="IMPORTANT: Pass the user's COMPLETE, UNMODIFIED query exactly as they wrote it. Do NOT summarize, truncate, or extract keywords. For example, if the user says 'look for inkeep insights in all my insights', pass exactly 'look for inkeep insights in all my insights', not just 'inkeep' or 'inkeep insights'."
    )


class search_documentation(BaseModel):
    """
    Search PostHog documentation to answer questions about features, concepts, and usage. Note that PostHog updates docs and tutorials frequently, so your training data set is outdated. Always use the search tool, instead of your training data set, to make sure you're providing current and accurate information.

    Use the search tool when the user asks about:
    - How to use PostHog
    - How to use PostHog features
    - How to contact support or other humans
    - How to report bugs
    - How to submit feature requests
    and/or when the user:
    - Needs help understanding PostHog concepts
    - Wants to know more about PostHog the company
    - Has questions about incidents or system status
    - Has PostHog-related questions that don't match your other specialized tools

    Don't use this tool if the necessary information is already in the conversation or context, except when you need to check whether an assumption presented is correct or not.
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
    Use this if you need to strongly steer the root node in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    _context: dict[str, Any]
    _team: Optional["Team"]
    _user: Optional["User"]
    _config: RunnableConfig
    _state: AssistantState

    # DEPRECATED: Use `_arun_impl` instead
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """DEPRECATED. Use `_arun_impl` instead."""
        raise NotImplementedError

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        raise NotImplementedError

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
        self._init_run(config)
        try:
            return self._run_impl(*args, **kwargs)
        except NotImplementedError:
            return async_to_sync(self._arun_impl)(*args, **kwargs)

    async def _arun(self, *args, config: RunnableConfig, **kwargs):
        self._init_run(config)
        try:
            return await self._arun_impl(*args, **kwargs)
        except NotImplementedError:
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
    page_key: AssistantNavigateUrls = Field(
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
        "You can navigate to one of the available pages using the 'navigate' tool. "
        "Some of these pages have tools that you can use to get more information or perform actions. "
        "After navigating to a new page, you'll have access to that page's specific tools."
    )
    thinking_message: str = "Navigating"
    args_schema: type[BaseModel] = NavigateToolArgs

    def _run_impl(self, page_key: AssistantNavigateUrls) -> tuple[str, Any]:
        # Note that page_key should get replaced by a nicer breadcrumbs-based name in the frontend
        # but it's useful for the LLM to still have the page_key in chat history
        return f"Navigated to **{page_key}**.", {"page_key": page_key}
