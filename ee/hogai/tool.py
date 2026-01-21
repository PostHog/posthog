import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from functools import cached_property
from string import Formatter
from typing import Any, Literal, Self

import structlog
from asgiref.sync import async_to_sync
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.types import interrupt
from pydantic import BaseModel

from posthog.schema import AssistantTool

from posthog.models import Team, User
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.core.context import get_node_path, set_node_path
from ee.hogai.core.mixins import AssistantContextMixin, AssistantDispatcherMixin
from ee.hogai.registry import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.tool_errors import MaxToolAccessDeniedError
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantState, NodePath

logger = structlog.get_logger(__name__)


class ToolMessagesArtifact(BaseModel):
    """Return messages directly. Use with `artifact`."""

    messages: Sequence[AssistantMessageUnion]


PENDING_APPROVAL_STATUS: Literal["pending_approval"] = "pending_approval"


class ApprovalRequest(BaseModel):
    """
    Interrupt payload when a tool operation requires user approval.
    This is passed to interrupt() and surfaced to the FE. When the user approves or rejects,
    """

    status: Literal["pending_approval"] = PENDING_APPROVAL_STATUS
    proposal_id: str
    tool_name: str
    preview: str
    payload: dict[str, Any]


class MaxTool(AssistantContextMixin, AssistantDispatcherMixin, BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    billable: bool = False
    """Whether LLM generations triggered by this tool should count toward billing."""

    context_prompt_template: str | None = None
    """The template for context associated with this tool, that will be injected into the root node's context messages.
    Use this if you need to strongly steer the root node in deciding _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    _config: RunnableConfig
    _state: AssistantState
    _context_manager: AssistantContextManager
    _node_path: tuple[NodePath, ...]

    # DEPRECATED: Use `_arun_impl` instead
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """DEPRECATED. Use `_arun_impl` instead."""
        raise NotImplementedError

    async def _arun_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        raise NotImplementedError

    async def is_dangerous_operation(self, *args, **kwargs) -> bool:
        """
        Override to mark certain operations as requiring user approval.

        Returns True if the operation should require explicit user approval
        before being executed. The default implementation returns False.
        """
        return False

    async def format_dangerous_operation_preview(self, *args, **kwargs) -> str:
        """
        Override to provide a human-readable preview of the dangerous operation.
        This is shown to the user when asking for approval. Should clearly
        describe what will happen if the operation is approved.

        This method can make async calls (e.g., database queries) to build a rich preview.
        """
        return f"Execute {self.name} operation"

    def _get_conversation_id(self) -> str | None:
        """Extract conversation_id from the config."""
        configurable = self._config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        # Ensure we return a string for consistent cache key matching
        return str(thread_id) if thread_id is not None else None

    @property
    def _original_tool_call_id(self) -> str | None:
        """Get the original tool_call_id from the AssistantMessage that invoked this tool."""
        if self._node_path:
            # Find the first NodePath with a tool_call_id
            for path in reversed(self._node_path):
                if path.tool_call_id:
                    return path.tool_call_id
        return None

    # -------------------------------------------------------------------------
    # Access Control (Resource-level)
    # -------------------------------------------------------------------------
    # TODO: Implement object-level access check after retrieval in the ArtifactManager

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        """Access control instance for checking user permissions."""
        return UserAccessControl(
            user=self._user,
            team=self._team,
            organization_id=str(self._team.organization_id),
        )

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
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
        if node_path is None:
            self._node_path = get_node_path() or ()
        else:
            self._node_path = node_path
        self._state = state if state else AssistantState(messages=[])
        self._config = config if config else RunnableConfig(configurable={})
        self._context_manager = context_manager or AssistantContextManager(team, user, self._config)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.endswith("Tool"):
            raise ValueError("The name of a MaxTool subclass must end with 'Tool', for clarity")
        try:
            accepted_name = AssistantTool(cls.name)
        except ValueError:
            raise ValueError(
                f"MaxTool name '{cls.name}' is not a recognized AssistantTool value. Fix this name, or update AssistantTool in schema-assistant-messages.ts and run `pnpm schema:build`"
            )
        CONTEXTUAL_TOOL_NAME_TO_TOOL[accepted_name] = cls

    def _run(self, *args, config: RunnableConfig, **kwargs):
        """LangChain default runner."""
        self._check_access_control()
        try:
            return self._run_with_context(*args, **kwargs)
        except NotImplementedError:
            pass
        return async_to_sync(self._arun_with_context)(*args, **kwargs)

    async def _arun(self, *args, config: RunnableConfig, **kwargs):
        """LangChain default runner."""
        # using database_sync_to_async because UserAccessControl is fully sync
        await database_sync_to_async(self._check_access_control)()
        try:
            return await self._arun_with_context(*args, **kwargs)
        except NotImplementedError:
            pass
        return await super()._arun(*args, config=config, **kwargs)

    def _run_with_context(self, *args, **kwargs):
        """Sets the context for the tool."""
        with set_node_path(self.node_path):
            if permission_check_result := async_to_sync(self._check_dangerous_operation)(**kwargs):
                return permission_check_result
            return self._run_impl(*args, **kwargs)

    async def _arun_with_context(self, *args, **kwargs):
        """Sets the context for the tool. Checks for approved/dangerous operations before executing."""
        with set_node_path(self.node_path):
            if permission_check_result := await self._check_dangerous_operation(**kwargs):
                return permission_check_result
            return await self._arun_impl(*args, **kwargs)

    def get_required_resource_access(self) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        """
        Declare what resource-level access this tool requires to be used.

        Override this method to specify access requirements for your tool.
        The check runs before `_arun_impl` is called.

        Returns:
            List of (resource, required_level) tuples.
            Empty list means no access control check (default for backward compatibility).

        Examples:
            # Tool that creates feature flags
            return [("feature_flag", "editor")]

            # Tool that reads insights
            return [("insight", "viewer")]

            # Tool that needs multiple permissions
            return [("dashboard", "editor"), ("insight", "viewer")]
        """
        return []

    @property
    def node_name(self) -> str:
        return f"max_tool.{self.get_name()}"

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return (*self._node_path, NodePath(name=self.node_name))

    @property
    def context(self) -> dict:
        return self._context_manager.get_contextual_tools().get(self.get_name(), {})

    def format_context_prompt_injection(self, context: dict[str, Any]) -> str | None:
        if not self.context_prompt_template:
            return None
        # Build initial context
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        # Extract expected keys from template
        expected_keys = {
            field for _, field, _, _ in Formatter().parse(self.context_prompt_template) if field is not None
        }
        # If they expect key is not present in the context (for example, cached FE) - use None as a default
        for key in expected_keys:
            if key not in formatted_context:
                formatted_context[key] = None
                logger.warning(
                    f"Context prompt template for {self.get_name()} expects key {key} but it is not present in the context"
                )
        return self.context_prompt_template.format(**formatted_context)

    def set_node_path(self, node_path: tuple[NodePath, ...]):
        self._node_path = node_path

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        """
        Factory that creates a tool class.

        Override this factory to dynamically modify the tool name, description, args schema, etc.
        """
        return cls(
            team=team, user=user, node_path=node_path, state=state, config=config, context_manager=context_manager
        )

    def _check_access_control(self) -> None:
        """
        Checks all resource-level access requirements declared in `get_required_resource_access()`.
        Raises MaxToolAccessDeniedError if any check fails.
        """
        required_access = self.get_required_resource_access()
        if not required_access:
            return

        for resource, required_level in required_access:
            if not self.user_access_control.check_access_level_for_resource(resource, required_level):
                raise MaxToolAccessDeniedError(resource, required_level, action="use")

    async def _check_dangerous_operation(self, **kwargs) -> tuple[str, Any] | None:
        if not await self.is_dangerous_operation(**kwargs):
            return None

        # Handle dangerous operation approval flow
        # Pre-compute preview before calling _handle_dangerous_operation
        preview = await self.format_dangerous_operation_preview(**kwargs)
        dangerous_result = self._handle_dangerous_operation(preview=preview, **kwargs)
        if dangerous_result is not None:
            return dangerous_result
        return None

    def _handle_dangerous_operation(self, preview: str | None = None, **kwargs) -> tuple[str, Any] | None:
        """
        Handle dangerous operation approval flow using LangGraph's interrupt().

        If the operation is dangerous, this method calls interrupt() which pauses execution
        and returns an ApprovalRequest to the frontend. When the user approves or rejects,
        the graph is resumed with a Command(resume=payload) and interrupt() returns that payload.

        Args:
            preview: Human-readable preview of the operation. Must be provided when the operation
                     is dangerous (pre-computed async by the caller).
        """
        if preview is None:
            raise ValueError("preview must be provided for dangerous operations")

        proposal_id = str(uuid.uuid4())
        serialized_payload = self._serialize_kwargs_for_storage(kwargs)

        approval_request = ApprovalRequest(
            proposal_id=proposal_id,
            tool_name=self.name,
            preview=preview,
            payload=serialized_payload,
        )

        # Call interrupt() - execution pauses here and ApprovalRequest is sent to frontend
        # When resumed with Command(resume=response), interrupt() returns the response
        response = interrupt(
            {
                **approval_request.model_dump(),
                # Include original tool_call_id for proper card positioning on reload
                "original_tool_call_id": self._original_tool_call_id,
            }
        )

        # Handle the response from the user
        if isinstance(response, dict) and response.get("action") == "approve":
            # User approved - update kwargs with any modifications and proceed
            updated_payload = response.get("payload", serialized_payload)
            kwargs.update(self._reconstruct_kwargs_from_payload(updated_payload))
            return None  # Continue with _arun_impl
        else:
            # User rejected
            feedback = response.get("feedback", "") if isinstance(response, dict) else ""
            if feedback:
                return (
                    f"The user rejected this operation with the following feedback: {feedback}. "
                    "Please acknowledge their feedback and adjust your approach accordingly.",
                    None,
                )
            return (
                "The user rejected this operation. "
                "Please acknowledge their decision and ask if they would like to proceed differently.",
                None,
            )

    def _reconstruct_kwargs_from_payload(self, payload: dict) -> dict:
        """Reconstruct kwargs from stored payload (Pydantic deserialization)."""
        args_schema = getattr(self, "args_schema", None)
        if args_schema is not None and isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
            try:
                validated_args = args_schema.model_validate(payload)
                return {field_name: getattr(validated_args, field_name) for field_name in validated_args.model_fields}
            except Exception as e:
                logger.warning(f"Failed to reconstruct kwargs from payload: {e}, using raw payload")
        return payload

    def _serialize_kwargs_for_storage(self, kwargs: dict) -> dict:
        """Serialize kwargs for cache storage, converting Pydantic models to dicts."""
        serialized = {}
        for key, value in kwargs.items():
            if isinstance(value, BaseModel):
                serialized[key] = value.model_dump()
            else:
                serialized[key] = value
        return serialized


class MaxSubtool(AssistantDispatcherMixin, ABC):
    _config: RunnableConfig

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        state: AssistantState,
        config: RunnableConfig,
        context_manager: AssistantContextManager,
        node_path: tuple[NodePath, ...] | None = None,
    ):
        self._team = team
        self._user = user
        self._state = state
        self._context_manager = context_manager
        self._node_path = node_path or get_node_path() or ()

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        pass

    @property
    def node_name(self) -> str:
        return f"max_subtool.{self.__class__.__name__}"

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return self._node_path
