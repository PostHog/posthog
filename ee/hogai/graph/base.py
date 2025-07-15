import datetime
from abc import ABC
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from django.utils import timezone
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.exceptions import GenerationCanceled
from ee.hogai.utils.helpers import find_last_ui_context
from ee.models import Conversation, CoreMemory
from posthog.models import Team
from posthog.models.user import User
from posthog.schema import AssistantMessage, AssistantToolCall, MaxUIContext, MaxBillingContext
from posthog.sync import database_sync_to_async

from ..utils.types import AssistantMessageUnion, AssistantState, PartialAssistantState


class AssistantNode(ABC):
    _team: Team
    _user: User

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    async def __call__(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        """
        Run the assistant node and handle cancelled conversation before the node is run.
        """
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if thread_id and await self._is_conversation_cancelled(thread_id):
            raise GenerationCanceled
        try:
            return await self.arun(state, config)
        except NotImplementedError:
            return await database_sync_to_async(self.run, thread_sensitive=False)(state, config)

    # DEPRECATED: Use `arun` instead
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        """DEPRECATED. Use `arun` instead."""
        raise NotImplementedError

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        raise NotImplementedError

    async def _aget_conversation(self, conversation_id: UUID) -> Conversation | None:
        try:
            return await Conversation.objects.aget(team=self._team, id=conversation_id)
        except Conversation.DoesNotExist:
            return None

    def _get_conversation(self, conversation_id: UUID) -> Conversation | None:
        try:
            return Conversation.objects.get(team=self._team, id=conversation_id)
        except Conversation.DoesNotExist:
            return None

    async def _aget_core_memory(self) -> CoreMemory | None:
        try:
            return await CoreMemory.objects.aget(team=self._team)
        except CoreMemory.DoesNotExist:
            return None

    @property
    def core_memory(self) -> CoreMemory | None:
        try:
            return CoreMemory.objects.get(team=self._team)
        except CoreMemory.DoesNotExist:
            return None

    @property
    def core_memory_text(self) -> str:
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

    async def _is_conversation_cancelled(self, conversation_id: UUID) -> bool:
        conversation = await self._aget_conversation(conversation_id)
        if not conversation:
            raise ValueError(f"Conversation {conversation_id} not found")
        return conversation.status == Conversation.Status.CANCELING

    def _get_tool_call(self, messages: Sequence[AssistantMessageUnion], tool_call_id: str) -> AssistantToolCall:
        for message in reversed(messages):
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                continue
            for tool_call in message.tool_calls:
                if tool_call.id == tool_call_id:
                    return tool_call
        raise ValueError(f"Tool call {tool_call_id} not found in state")

    def _get_contextual_tools(self, config: RunnableConfig) -> dict[str, Any]:
        """
        Extracts contextual tools from the runnable config.
        """
        contextual_tools = (config.get("configurable") or {}).get("contextual_tools") or {}
        if not isinstance(contextual_tools, dict):
            raise ValueError("Contextual tools must be a dictionary of tool names to tool context")
        return contextual_tools

    def _get_ui_context(self, state: AssistantState) -> MaxUIContext | None:
        """
        Extracts the UI context from the latest human message.
        """
        return find_last_ui_context(state.messages)

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

    def _get_billing_context(self, config: RunnableConfig) -> MaxBillingContext | None:
        """
        Extracts the billing context from the runnable config.
        """
        billing_context = (config.get("configurable") or {}).get("billing_context")
        if not billing_context:
            return None
        return MaxBillingContext.model_validate(billing_context)
