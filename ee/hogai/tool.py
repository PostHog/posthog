import json
import inspect
import pkgutil
import importlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

import structlog
from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field, create_model
from pydantic.json_schema import SkipJsonSchema

from posthog.schema import AssistantContextualTool, AssistantToolCallMessage

from posthog.models import Team, User

import products

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantMessageUnion

CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantContextualTool, type["MaxTool"]] = {}

logger = structlog.get_logger(__name__)


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


"""Error Handling Strategy:

  - MaxToolError: Permanent failures, LLM should not retry
  - MaxToolRetryableError: Transient failures, LLM may retry with adjusted inputs
  - Generic Exception: Unknown failures, treated as permanent (no retry hint)

  All errors produce hidden tool messages visible to LLM but not end users.
  """


class MaxToolError(Exception):
    """Non-retryable tool error. Raise this for permanent failures that LLM should not immediately retry."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code

    @property
    def retryable(self) -> bool:
        return False


class MaxToolRetryableError(MaxToolError):
    """Retryable tool error. Raise for transient failures (timeouts, rate limits, temporary unavailability)."""

    @property
    def retryable(self) -> bool:
        return True


_logger = structlog.get_logger(__name__)


def _summarize_exception(e: Exception) -> str:
    name = e.__class__.__name__
    msg = str(e).strip()
    if len(msg) > 500:
        msg = msg[:500] + "…"
    return f"{name}: {msg}"


def _filter_kwargs_for(func: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Compatibility shim: support legacy tools that don't accept newly injected kwargs.

    We now inject `tool_call_id` into all tool arg schemas so the runtime always has the id
    for error-to-message conversion. Some existing tools still implement `_run_impl` (sync)
    or `_arun_impl` (async) without a `tool_call_id` parameter. Filtering prevents TypeErrors
    by only passing kwargs that the callee actually accepts.
    """
    try:
        sig = inspect.signature(func)
        return {k: v for k, v in kwargs.items() if k in sig.parameters}
    except Exception:
        # If inspection fails for any reason, be permissive.
        return kwargs


class MaxToolArgs(BaseModel):
    """Base arguments schema for all MaxTools that provides an injected tool call id."""

    tool_call_id: Annotated[str, InjectedToolCallId, SkipJsonSchema]


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
        # Ensure every tool has the injected tool_call_id in its args schema
        if args_schema is None:
            tool_kwargs["args_schema"] = MaxToolArgs
        else:
            annotations = getattr(args_schema, "__annotations__", {}) or {}
            if "tool_call_id" not in annotations:
                ExtendedArgs = create_model(  # type: ignore[call-arg]
                    f"{args_schema.__name__}WithToolCallId",
                    __base__=args_schema,
                    tool_call_id=(Annotated[str, InjectedToolCallId, SkipJsonSchema], ...),
                )
                tool_kwargs["args_schema"] = ExtendedArgs
            else:
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
            filtered_kwargs = _filter_kwargs_for(self._run_impl, kwargs)
            return self._run_impl(*args, **filtered_kwargs)
        except NotImplementedError:
            pass
        return async_to_sync(self._arun_impl)(*args, **kwargs)

    async def _arun(self, *args, config: RunnableConfig, **kwargs):
        try:
            filtered_kwargs = _filter_kwargs_for(self._arun_impl, kwargs)
            return await self._arun_impl(*args, **filtered_kwargs)

        except NotImplementedError:
            pass
        except MaxToolError as e:
            tool_call_id = kwargs.get("tool_call_id") or ""
            if not tool_call_id:
                logger.warning("maxtool_error", tool=self.get_name(), error=str(e))
            capture_exception(
                e,
                distinct_id=str(self._user.distinct_id),
                properties={"tool": self.get_name(), "retryable": e.retryable, "code": getattr(e, "code", None)},
            )
            retry_hint = " You may retry with adjusted inputs." if e.retryable else ""
            content = f"Tool failed: {_summarize_exception(e)}.{retry_hint}"
            return "", ToolMessagesArtifact(
                messages=[
                    AssistantToolCallMessage(
                        content=content,
                        id=str(uuid4()),
                        tool_call_id=tool_call_id,
                        visible=False,
                    )
                ]
            )
        except Exception as e:
            tool_call_id = kwargs.get("tool_call_id") or ""
            capture_exception(e, distinct_id=str(self._user.distinct_id), properties={"tool": self.get_name()})
            content = f"Tool crashed: {_summarize_exception(e)}."
            return "", ToolMessagesArtifact(
                messages=[
                    AssistantToolCallMessage(
                        content=content,
                        id=str(uuid4()),
                        tool_call_id=tool_call_id,
                        visible=False,
                    )
                ]
            )
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


class MaxSubtool(ABC):
    def __init__(self, team: Team, user: User, state: AssistantState, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._state = state
        self._context_manager = context_manager

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        pass
