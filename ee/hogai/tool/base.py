import os
import json
import pkgutil
import importlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path
from typing import Any, final

import structlog
from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, create_model

from posthog.schema import AssistantTool, ToolExecutionStatus

from posthog.models import Team, User

import products

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import BaseState, ToolArtifact, ToolResult

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

    # Import tool.py files from ee/hogai/graph subdirectories
    graph_path = Path("ee/hogai/graph")
    if graph_path.exists():
        for tool_path in graph_path.rglob("tool.py"):
            # Skip test directories
            if "test" in tool_path.parts or "__pycache__" in tool_path.parts:
                continue

            # Convert path to module name
            module_path = str(tool_path.with_suffix("")).replace(os.sep, ".")
            try:
                importlib.import_module(module_path)
            except (ModuleNotFoundError, ImportError):
                pass  # Skip if module can't be imported


def get_assistant_tool_class(tool_name: str) -> type["MaxTool"] | None:
    """Get the tool class for a given tool name, handling circular import."""
    _import_assistant_tools()  # Ensure max_tools are imported
    from ee.hogai.tool import ASSISTANT_TOOL_NAME_TO_TOOL

    return ASSISTANT_TOOL_NAME_TO_TOOL[AssistantTool(tool_name)]


ToolUpdateCallback = Callable[[str, str | None, list[str] | None], Coroutine[Any, Any, None]]


class WithToolCallExplanation(BaseModel):
    tool_call_explanation: str
    """A short complete declarative explanation to show the user what the tool call is doing.
    Good: 'Create a trends insight to analyze user engagement'.
    Bad: 'I'm creating a trends insight because the user asked me to do it'.
    DO NOT use punctuation."""


class MaxTool(AssistantContextMixin, ABC):
    """
    Base class for all AI assistant tools.
    Read the README.md for more information on how to create a new AI assistant tool.
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

    _context: dict[str, Any]
    _config: RunnableConfig
    _state: BaseState | None
    _tool_call_id: str
    _tool_call_name: str
    _tool_call_description: str
    _tool_update_callback: ToolUpdateCallback | None

    def run(self, tool_call_id: str, parameters: dict[str, Any], config: RunnableConfig) -> ToolResult:
        self._init_run(tool_call_id, config)
        self._init_parameters(parameters)
        return async_to_sync(self._arun_impl)(**parameters)

    async def arun(self, tool_call_id: str, parameters: dict[str, Any], config: RunnableConfig) -> ToolResult:
        self._init_run(tool_call_id, config)
        self._init_parameters(parameters)
        return await self._arun_impl(**parameters)

    def format_context_prompt(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.system_prompt_template.format(**formatted_context)

    def get_tool_function_description(self) -> type[BaseModel]:
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
        if not hasattr(self, "_context"):
            raise AttributeError("Tool has not been run yet")
        return self._context

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        state: BaseState | None = None,
        tool_update_callback: ToolUpdateCallback | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._team = team
        self._user = user
        self._state = state
        self._tool_update_callback = tool_update_callback

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

    def _init_run(self, tool_call_id: str, config: RunnableConfig):
        configurable = config["configurable"]  # type: ignore
        self._tool_call_id = tool_call_id
        self._context = configurable.get("contextual_tools", {}).get(self.name, {})
        self._team = configurable["team"]
        self._user = configurable["user"]
        self._config = {
            "recursion_limit": 48,
            "callbacks": config.get("callbacks", []),
            "configurable": {
                "thread_id": configurable.get("thread_id"),
                "trace_id": configurable.get("trace_id"),
                "distinct_id": configurable.get("distinct_id"),
                "team": self._team,
                "user": self._user,
            },
        }

    def _init_parameters(self, parameters: dict[str, Any]) -> None:
        parameters.pop("tool_call_explanation", None)

    def format_system_prompt_injection(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.system_prompt_template.format(**formatted_context)

    async def _failed_execution(self, reason: str | None = None, metadata: dict[str, Any] | None = None) -> ToolResult:
        await self._update_tool_call_status(None)
        return ToolResult(
            id=self._tool_call_id,
            content=reason or "The tool failed to execute",
            artifacts=[],
            metadata=metadata,
            status=ToolExecutionStatus.FAILED,
            tool_name=self.name,
            send_result_to_frontend=self.send_result_to_frontend,
        )

    async def _successful_execution(
        self, content: str, artifacts: Sequence[ToolArtifact] | None = None, metadata: dict[str, Any] | None = None
    ) -> ToolResult:
        await self._update_tool_call_status(None)
        return ToolResult(
            id=self._tool_call_id,
            content=content,
            artifacts=artifacts or [],
            metadata=metadata,
            status=ToolExecutionStatus.COMPLETED,
            tool_name=self.name,
            send_result_to_frontend=self.send_result_to_frontend,
        )

    async def _update_tool_call_status(self, content: str | None, substeps: list[str] | None = None) -> None:
        logger.info(f"Updating tool call status: {self._tool_call_id}, {content}, {substeps}")
        if self._tool_update_callback:
            await self._tool_update_callback(self._tool_call_id, content, substeps)
