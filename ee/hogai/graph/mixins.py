import datetime
from abc import ABC
from typing import Any
from uuid import UUID

from django.utils import timezone
from langchain_core.runnables import RunnableConfig

from ee.models import Conversation, CoreMemory
from posthog.models import Team
from posthog.models.user import User


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

    def _get_debug_props(self, config: RunnableConfig) -> dict[str, Any]:
        """Properties to be sent to PostHog SDK (error tracking, etc)."""
        return {
            "$session_id": self._get_session_id(config),
            "$ai_trace_id": self._get_trace_id(config),
            "thread_id": self._get_thread_id(config),
            "tag": "max_ai",
        }

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
