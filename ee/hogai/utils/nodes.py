import datetime
from abc import ABC, abstractmethod

from django.utils import timezone
from langchain_core.runnables import RunnableConfig

from ee.models.assistant import CoreMemory
from posthog.models.team.team import Team

from .types import AssistantState, PartialAssistantState


class AssistantNode(ABC):
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    @abstractmethod
    def run(cls, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        raise NotImplementedError

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
    def project_tz_now(self) -> str:
        """
        Returns the current time in the project's timezone.
        """
        return self._utc_now_datetime.astimezone(self._team.timezone_info).strftime("%Y-%m-%d %H:%M:%S")

    @property
    def project_timezone(self) -> str | None:
        """
        Returns the timezone of the project.
        """
        return self._team.timezone_info.tzname(self._utc_now_datetime)
