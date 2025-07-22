import datetime
from abc import ABC, abstractmethod
from uuid import UUID

from django.utils import timezone

from ee.models import Conversation, CoreMemory
from posthog.models import Team
from posthog.models.user import User


class AssistantContextMixin(ABC):
    @property
    @abstractmethod
    def _team(self) -> Team: ...

    @property
    @abstractmethod
    def _user(self) -> User: ...

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
