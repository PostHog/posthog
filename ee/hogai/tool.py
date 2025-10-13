import json
import pkgutil
import importlib
from collections.abc import Sequence
from typing import Any, Literal, Self

from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from posthog.schema import AssistantContextualTool

from posthog.models import Team, User

import products

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion

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


class ToolMessagesArtifact(BaseModel):
    """Return messages directly. Use with `artifact`."""

    messages: Sequence[AssistantMessageUnion]


class MaxTool(AssistantContextMixin, BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    thinking_message: str
    """The message shown to let the user know this tool is being used. One sentence, no punctuation.
    For example, "Updating filters"
    """

    context_prompt_template: str = "No context provided for this tool."
    """The template for context associated with this tool, that will be injected into the root node's context messages.
    Use this if you need to strongly steer the root node in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    show_tool_call_message: bool = Field(description="Whether to show tool call messages.", default=True)

    _config: RunnableConfig
    _state: AssistantState
    _context_manager: AssistantContextManager

    # DEPRECATED: Use `_arun_impl` instead
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """DEPRECATED. Use `_arun_impl` instead."""
        raise NotImplementedError

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        raise NotImplementedError

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        name: str | None = None,
        description: str | None = None,
        args_schema: type[BaseModel] | None = None,
        context_manager: AssistantContextManager | None = None,
        **kwargs,
    ):
        tool_kwargs: dict[str, Any] = {}
        if name is not None:
            tool_kwargs["name"] = name
        if description is not None:
            tool_kwargs["description"] = description
        if args_schema is not None:
            tool_kwargs["args_schema"] = args_schema

        super().__init__(**tool_kwargs, **kwargs)
        self._team = team
        self._user = user
        self._state = state if state else AssistantState(messages=[])
        self._config = config if config else RunnableConfig(configurable={})
        self._context_manager = context_manager or AssistantContextManager(team, user, self._config)

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
        try:
            return self._run_impl(*args, **kwargs)
        except NotImplementedError:
            pass
        return async_to_sync(self._arun_impl)(*args, **kwargs)

    async def _arun(self, *args, config: RunnableConfig, **kwargs):
        try:
            return await self._arun_impl(*args, **kwargs)
        except NotImplementedError:
            pass
        return await super()._arun(*args, config=config, **kwargs)

    @property
    def context(self) -> dict:
        return self._context_manager.get_contextual_tools().get(self.get_name(), {})

    def format_context_prompt_injection(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.context_prompt_template.format(**formatted_context)

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
    ) -> Self:
        """
        Factory that creates a tool class.

        Override this factory to dynamically modify the tool name, description, args schema, etc.
        """
        return cls(team=team, user=user, state=state, config=config)
