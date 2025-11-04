import datetime
from abc import ABC, abstractmethod
from typing import Any, get_args, get_origin
from uuid import UUID

from django.utils import timezone

from langchain_core.runnables import RunnableConfig

from posthog.schema import CurrencyCode

from posthog.event_usage import groups
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.user import User

from ee.hogai.utils.dispatcher import AssistantDispatcher, create_dispatcher_from_config
from ee.hogai.utils.types.base import BaseStateWithIntermediateSteps, NodePath
from ee.models import Conversation, CoreMemory


class AssistantContextMixin(ABC):
    _team: Team
    _user: User

    async def _aget_core_memory(self) -> CoreMemory | None:
        try:
            return await CoreMemory.objects.aget(team=self._team)
        except CoreMemory.DoesNotExist:
            return None

    async def _aget_core_memory_text(self) -> str:
        core_memory = await self._aget_core_memory()
        if not core_memory:
            return ""
        return core_memory.formatted_text

    async def _aget_conversation(self, conversation_id: UUID) -> Conversation | None:
        try:
            return await Conversation.objects.aget(team=self._team, id=conversation_id)
        except Conversation.DoesNotExist:
            return None

    def _get_conversation(self, conversation_id: UUID) -> Conversation | None:
        """Deprecated. Use `_aget_conversation` instead."""
        try:
            return Conversation.objects.get(team=self._team, id=conversation_id)
        except Conversation.DoesNotExist:
            return None

    @property
    def core_memory(self) -> CoreMemory | None:
        """Deprecated. Use `_aget_core_memory` instead."""
        try:
            return CoreMemory.objects.get(team=self._team)
        except CoreMemory.DoesNotExist:
            return None

    @property
    def core_memory_text(self) -> str:
        """Deprecated. Use `_aget_core_memory_text` instead."""
        if not self.core_memory:
            return ""
        return self.core_memory.formatted_text

    @property
    def _utc_now_datetime(self) -> datetime.datetime:
        return timezone.now().astimezone(datetime.UTC)

    @property
    def utc_now(self) -> str:
        """
        Returns the current time in UTC.
        """
        return self._utc_now_datetime.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def project_now(self) -> str:
        """
        Returns the current time in the project's timezone.
        """
        return self._utc_now_datetime.astimezone(self._team.timezone_info).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def project_timezone(self) -> str | None:
        """
        Returns the timezone of the project, e.g. "PST" or "UTC".
        """
        return self._team.timezone_info.tzname(self._utc_now_datetime)

    @property
    def project_currency(self) -> str:
        """
        Returns the currency of the project, e.g. "USD" or "EUR".
        """
        return self._team.base_currency or CurrencyCode.USD.value

    def _get_debug_props(self, config: RunnableConfig) -> dict[str, Any]:
        """Properties to be sent to PostHog SDK (error tracking, etc)."""
        metadata = (config.get("configurable") or {}).get("sdk_metadata")
        debug_props = {
            "$session_id": self._get_session_id(config),
            "$ai_trace_id": self._get_trace_id(config),
            "thread_id": self._get_thread_id(config),
            "$groups": groups(team=self._team),
        }
        if metadata:
            debug_props.update(metadata)
        return debug_props

    def _get_user_distinct_id(self, config: RunnableConfig) -> Any | None:
        """
        Extracts the user distinct ID from the runnable config.
        """
        return (config.get("configurable") or {}).get("distinct_id") or None

    def _get_trace_id(self, config: RunnableConfig) -> Any | None:
        """
        Extracts the trace ID from the runnable config.
        """
        return (config.get("configurable") or {}).get("trace_id") or None

    def _get_session_id(self, config: RunnableConfig) -> Any | None:
        """
        Extracts the session ID from the runnable config.
        """
        return (config.get("configurable") or {}).get("session_id") or None

    def _get_thread_id(self, config: RunnableConfig) -> Any | None:
        """
        Extracts the thread ID from the runnable config.
        """
        return (config.get("configurable") or {}).get("thread_id") or None


class StateClassMixin:
    """Mixin to extract state types from generic class parameters."""

    def _get_state_class(self, target_class: type) -> tuple[type, type]:
        """Extract the State type from the class's generic parameters."""
        # Check if this class has generic arguments
        if hasattr(self.__class__, "__orig_bases__"):
            for base in self.__class__.__orig_bases__:
                if get_origin(base) is target_class:
                    args = get_args(base)
                    if args:
                        return args[0], args[1]  # State is the first argument and PartialState is the second argument

        # No generic type found - this shouldn't happen in proper usage
        raise ValueError(
            f"Could not determine state type for {self.__class__.__name__}. "
            f"Make sure to inherit from {target_class.__name__} with a specific state type, "
            f"e.g., {target_class.__name__}[StateType, PartialStateType]"
        )


class TaxonomyUpdateDispatcherNodeMixin:
    _team: Team
    _user: User
    dispatcher: AssistantDispatcher

    def dispatch_update_message(self, state: BaseStateWithIntermediateSteps) -> None:
        substeps: list[str] = []
        if intermediate_steps := state.intermediate_steps:
            for action, _ in intermediate_steps:
                assert isinstance(action.tool_input, dict)
                match action.tool:
                    case "retrieve_event_properties":
                        substeps.append(f"Exploring `{action.tool_input['event_name']}` event's properties")
                    case "retrieve_entity_properties":
                        substeps.append(f"Exploring {action.tool_input['entity']} properties")
                    case "retrieve_event_property_values":
                        substeps.append(
                            f"Analyzing `{action.tool_input['event_name']}` event's property `{action.tool_input['property_name']}`"
                        )
                    case "retrieve_entity_property_values":
                        substeps.append(
                            f"Analyzing {action.tool_input['entity']} property `{action.tool_input['property_name']}`"
                        )
                    case "retrieve_action_properties" | "retrieve_action_property_values":
                        try:
                            action_model = Action.objects.get(
                                pk=action.tool_input["action_id"], team__project_id=self._team.project_id
                            )
                            if action.tool == "retrieve_action_properties":
                                substeps.append(f"Exploring `{action_model.name}` action properties")
                            elif action.tool == "retrieve_action_property_values":
                                substeps.append(
                                    f"Analyzing `{action.tool_input['property_name']}` action property of `{action_model.name}`"
                                )
                        except Action.DoesNotExist:
                            pass

        content = "Picking relevant events and properties"
        if substeps:
            content = substeps[-1]
        self.dispatcher.update(content)


class AssistantDispatcherMixin(ABC):
    _node_path: tuple[NodePath, ...]
    _config: RunnableConfig | None
    _dispatcher: AssistantDispatcher | None = None

    @property
    def node_path(self) -> tuple[NodePath, ...]:
        return self._node_path

    @property
    @abstractmethod
    def node_name(self) -> str: ...

    @property
    def tool_call_id(self) -> str | None:
        parent_tool_call_id = next((path.tool_call_id for path in reversed(self._node_path) if path.tool_call_id), None)
        return parent_tool_call_id

    @property
    def dispatcher(self) -> AssistantDispatcher:
        """Create a dispatcher for this node"""
        if self._dispatcher:
            return self._dispatcher
        self._dispatcher = create_dispatcher_from_config(self._config or {}, self.node_path)
        return self._dispatcher
