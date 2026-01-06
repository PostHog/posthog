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
from pydantic import BaseModel

from posthog.schema import AssistantTool

from posthog.models import Team, User
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.core.context import get_node_path, set_node_path
from ee.hogai.core.mixins import AssistantContextMixin, AssistantDispatcherMixin
from ee.hogai.pending_operations import (
    delete_pending_operation,
    get_approved_operation_for_conversation,
    store_pending_operation,
)
from ee.hogai.registry import CONTEXTUAL_TOOL_NAME_TO_TOOL
from ee.hogai.tool_errors import MaxToolAccessDeniedError
from ee.hogai.utils.types.base import AssistantMessageUnion, AssistantState, NodePath

logger = structlog.get_logger(__name__)


class ToolMessagesArtifact(BaseModel):
    """Return messages directly. Use with `artifact`."""

    messages: Sequence[AssistantMessageUnion]


class DangerousOperationResponse(BaseModel):
    """Response returned when a tool operation requires user approval."""

    status: Literal["pending_approval"] = "pending_approval"
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

    def is_dangerous_operation(self, **kwargs) -> bool:
        """
        Override to mark certain operations as requiring user approval.

        Returns True if the operation should require explicit user approval
        before being executed. The default implementation returns False.
        """
        return False

    def format_dangerous_operation_preview(self, **kwargs) -> str:
        """
        Override to provide a human-readable preview of the dangerous operation.
        This is shown to the user when asking for approval. Should clearly
        describe what will happen if the operation is approved.
        """
        return f"Execute {self.name} operation"

    def _get_conversation_id(self) -> str | None:
        """Extract conversation_id from the config."""
        configurable = self._config.get("configurable", {})
        return configurable.get("thread_id")

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
            return self._run_impl(*args, **kwargs)

    async def _arun_with_context(self, *args, **kwargs):
        """Sets the context for the tool. Checks for approved/dangerous operations before executing."""
        with set_node_path(self.node_path):
            # Handle dangerous operation approval flow
            dangerous_result = await self._handle_dangerous_operation(**kwargs)
            if dangerous_result is not None:
                return dangerous_result

            # Normal execution
            return await self._arun_impl(*args, **kwargs)

    async def _handle_dangerous_operation(self, **kwargs) -> tuple[str, Any] | None:
        """
        Handle dangerous operation approval flow.

        Returns:
            - tuple[str, Any]: Result if an approved operation was executed or approval is needed
            - None: If normal execution should proceed
        """
        conversation_id = self._get_conversation_id()

        # Check for approved operation - execute with stored payload
        if conversation_id:
            approved_op = get_approved_operation_for_conversation(conversation_id, self.name)
            if approved_op:
                delete_pending_operation(conversation_id, approved_op["proposal_id"])
                stored_kwargs = self._reconstruct_kwargs_from_payload(approved_op["payload"])
                return await self._arun_impl(**stored_kwargs)

        # Check if this operation requires approval
        if self.is_dangerous_operation(**kwargs):
            return await self._create_dangerous_operation_response(**kwargs)

        return None

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

    async def _create_dangerous_operation_response(self, **kwargs) -> tuple[str, Any] | None:
        """Create a dangerous operation response requiring user approval."""
        conversation_id = self._get_conversation_id()

        # Without conversation_id, we can't track approvals - fall through to normal execution
        if not conversation_id:
            logger.warning(
                "Cannot create dangerous operation response without conversation_id, executing without approval",
                tool_name=self.name,
            )
            return None

        proposal_id = str(uuid.uuid4())
        preview = self.format_dangerous_operation_preview(**kwargs)

        # Serialize kwargs for storage (Pydantic models -> dicts)
        serialized_payload = self._serialize_kwargs_for_storage(kwargs)

        await store_pending_operation(
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            tool_name=self.name,
            payload=serialized_payload,
        )

        response = DangerousOperationResponse(
            proposal_id=proposal_id,
            tool_name=self.name,
            preview=preview,
            payload=serialized_payload,
        )
        # LLM content and response dict as artifact for ui_payload
        return (
            "STOP. This operation requires explicit user approval before proceeding. "
            "The user is now seeing an approval dialog. Do NOT continue, do NOT summarize, do NOT say 'Done'. "
            "Wait silently for the user's response. "
            "When the user approves, call this tool again with the same arguments - it will execute normally.",
            response.model_dump(),
        )

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
