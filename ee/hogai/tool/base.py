import json
import pkgutil
import importlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, Self, final

import structlog
from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, create_model

from posthog.schema import AssistantTool, AssistantToolCallMessage, ToolExecutionStatus

from posthog.models import Team, User

import products

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.types import ToolArtifact, ToolResult
from ee.hogai.utils.types.composed import AssistantMaxGraphState

ASSISTANT_TOOL_NAME_TO_TOOL: dict[AssistantTool, type["MaxTool"]] = {}

logger = structlog.get_logger(__name__)


def _import_assistant_tools() -> None:
    """TRICKY: Dynamically import assistant_tools from all products and ee/hogai/graph subdirectories"""
    # Import from products
    for module_info in pkgutil.iter_modules(products.__path__):
        if module_info.name in ("conftest", "test"):
            continue  # We mustn't import test modules in prod
        try:
            importlib.import_module(f"products.{module_info.name}.backend.max_tools")
        except ModuleNotFoundError:
            pass  # Skip if backend or max_tools doesn't exist - note that the product's dir needs a top-level __init__.py

    # Import all MaxTools from ee/hogai/graph/root/tools
    try:
        importlib.import_module("ee.hogai.graph.root.tools")
    except (ModuleNotFoundError, ImportError):
        pass  # Skip if module can't be imported


def get_assistant_tool_class(tool_name: str) -> type["MaxTool"] | None:
    """Get the tool class for a given tool name, handling circular import."""
    _import_assistant_tools()  # Ensure max_tools are imported
    from ee.hogai.tool import ASSISTANT_TOOL_NAME_TO_TOOL

    # BUG FIX: Return None for unknown tool names instead of raising ValueError
    try:
        return ASSISTANT_TOOL_NAME_TO_TOOL[AssistantTool(tool_name)]
    except (ValueError, KeyError):
        return None


ToolUpdateCallback = Callable[[str, str | None, list[str] | None], Coroutine[Any, Any, None]]


class WithToolCallExplanation(BaseModel):
    tool_call_explanation: str
    """A short complete declarative explanation to show the user what the tool call is doing.
    Good: 'Create a trends insight to analyze user engagement'.
    Bad: 'I'm creating a trends insight because the user asked me to do it'.
    DO NOT use punctuation."""


class MaxToolMixin(ABC):
    """
    Base mixin to create MaxTools or MaxToolMixins.
    """

    name: str
    """The name of the tool."""
    description: str
    """The description of the tool, used by the agent to decide when to use the tool."""
    system_prompt_template: str = "No context provided for this tool."
    """The template for context associated with this tool, that will be provided as context to the agent.
    Use this if you need to strongly steer the agent in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """
    send_result_to_frontend: bool = False
    """
    "Whether to send result metadata to the frontend. Defaults to False."
    """

    args_schema: type[BaseModel] | None = None
    """The schema of the tool's arguments.
    If the tool does not take any arguments, set this to None.
    """
    _team: Team
    _user: User
    _config: RunnableConfig
    _state: AssistantMaxGraphState | None
    _context_manager: AssistantContextManager
    _tool_call_id: str
    _tool_call_name: str
    _tool_call_description: str
    _tool_update_callback: ToolUpdateCallback | None

    async def _failed_execution(self, reason: str | None = None, metadata: dict[str, Any] | None = None) -> ToolResult:
        raise NotImplementedError

    async def _successful_execution(
        self, content: str = "", artifacts: Sequence[ToolArtifact] | None = None, metadata: dict[str, Any] | None = None
    ) -> ToolResult:
        raise NotImplementedError

    async def _update_tool_call_status(self, content: str | None = None, substeps: list[str] | None = None) -> None:
        raise NotImplementedError


class MaxTool(AssistantContextMixin, MaxToolMixin, ABC):
    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        state: AssistantMaxGraphState,
        config: RunnableConfig,
        context_manager: AssistantContextManager,
    ) -> Self:
        """
        Factory that creates a tool class.

        Override this factory to dynamically modify the tool name, description, args schema, etc.
        """
        return cls(team=team, user=user, state=state, config=config, context_manager=context_manager)

    def run(
        self, tool_call_id: str, parameters: dict[str, Any], tool_update_callback: ToolUpdateCallback | None = None
    ) -> ToolResult:
        self._init_run(tool_call_id, parameters, tool_update_callback)
        return async_to_sync(self._arun_impl)(**parameters)

    async def arun(
        self, tool_call_id: str, parameters: dict[str, Any], tool_update_callback: ToolUpdateCallback | None = None
    ) -> ToolResult:
        self._init_run(tool_call_id, parameters, tool_update_callback)
        return await self._arun_impl(**parameters)

    def format_context_prompt(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.system_prompt_template.format(**formatted_context)

    @property
    def tool_function_description(self) -> type[BaseModel]:
        """
        Get the tool function Pydantic model, adding the name and description fields to the args_schema.

        These fields are added so that we can show the user what is being executed.
        """
        combined_fields = {}

        if self.args_schema:
            for field_name, field_info in self.args_schema.model_fields.items():
                combined_fields[field_name] = (field_info.annotation, field_info)

        CombinedModel = create_model(  # type: ignore[call-overload]
            self.name,
            __base__=WithToolCallExplanation,
            __module__=self.args_schema.__module__ if self.args_schema else BaseModel.__module__,
            **combined_fields,
        )

        CombinedModel.__doc__ = self.description

        return CombinedModel

    # DEPRECATED: Use `_arun_impl` instead
    @final
    def _run_impl(self, *args, **kwargs) -> ToolResult:
        """DEPRECATED. Use `_arun_impl` instead."""
        raise NotImplementedError

    @abstractmethod
    async def _arun_impl(self, *args, **kwargs) -> ToolResult:
        """Tool execution, which should return a ToolResult"""
        raise NotImplementedError

    @property
    def context(self) -> dict:
        return self._context_manager.get_tool_context(self.name)

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        state: AssistantMaxGraphState,
        config: RunnableConfig,
        context_manager: AssistantContextManager,
        name: str | None = None,
        description: str | None = None,
        args_schema: type[BaseModel] | None = None,
        **kwargs,
    ):
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if args_schema is not None:
            self.args_schema = args_schema
        for key, value in kwargs.items():
            setattr(self, key, value)

        self._team = team
        self._user = user
        self._state = state
        self._config = config
        self._context_manager = context_manager or AssistantContextManager(team, user, self._config)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.endswith("Tool"):
            raise ValueError("The name of a MaxTool subclass must end with 'Tool', for clarity")
        try:
            accepted_name = AssistantTool(cls.name)
        except ValueError:
            raise ValueError(
                f"MaxTool name '{cls.name}' is not a recognized AssistantContextualTool value. Fix this name, or update AssistantContextualTool in schema-assistant-messages.ts and run `pnpm schema:build`"
            )
        ASSISTANT_TOOL_NAME_TO_TOOL[accepted_name] = cls
        if not getattr(cls, "name", None) or not getattr(cls, "description", None):
            raise ValueError("You must set `name` and `description` on the tool")
        if cls.args_schema and getattr(cls.args_schema, "model_fields", {}).get("tool_call_explanation", None):
            raise ValueError("`tool_call_explanation` is a reserved field name")

    def _init_run(
        self, tool_call_id: str, parameters: dict[str, Any], tool_update_callback: ToolUpdateCallback | None = None
    ) -> None:
        self._tool_call_id = tool_call_id
        parameters.pop("tool_call_explanation", None)
        self._tool_update_callback = tool_update_callback

    @classmethod
    def format_system_prompt_injection(cls, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return cls.system_prompt_template.format(**formatted_context)

    async def _failed_execution(self, *args: Any, **kwargs: Any) -> ToolResult:
        reason: str | None = args[0] if len(args) > 0 else kwargs.get("reason")
        metadata: dict[str, Any] | None = args[1] if len(args) > 1 else kwargs.get("metadata")
        return ToolResult(
            id=self._tool_call_id,
            content=reason or "The tool failed to execute",
            artifacts=[],
            metadata=metadata,
            status=ToolExecutionStatus.FAILED,
            tool_name=self.name,
            send_result_to_frontend=self.send_result_to_frontend,
        )

    async def _successful_execution(self, *args: Any, **kwargs: Any) -> ToolResult:
        content: str = args[0] if len(args) > 0 else kwargs.get("content", "")
        artifacts: Sequence[ToolArtifact] | None = args[1] if len(args) > 1 else kwargs.get("artifacts")
        metadata: dict[str, Any] | None = args[2] if len(args) > 2 else kwargs.get("metadata")
        return ToolResult(
            id=self._tool_call_id,
            content=content,
            artifacts=artifacts or [],
            metadata=metadata,
            status=ToolExecutionStatus.COMPLETED,
            tool_name=self.name,
            send_result_to_frontend=self.send_result_to_frontend,
        )

    async def _update_tool_call_status(self, *args: Any, **kwargs: Any) -> None:
        content: str | None = args[0] if len(args) > 0 else kwargs.get("content")
        substeps: list[str] | None = args[1] if len(args) > 1 else kwargs.get("substeps")
        if self._tool_update_callback:
            await self._tool_update_callback(self._tool_call_id, content, substeps)

    async def _run_legacy_node(self, node_class: type[BaseAssistantNode]) -> ToolResult:
        """
        Run a legacy node-based tool that returns an AssistantToolCallMessage.
        """
        node = node_class(team=self._team, user=self._user)
        result = await node.arun(self._state, self._config)
        if not result or not result.messages:
            return await self._failed_execution()
        last_message = result.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            return await self._failed_execution()
        return await self._successful_execution(last_message.content, [])
