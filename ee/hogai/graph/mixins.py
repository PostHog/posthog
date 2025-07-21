from typing import TYPE_CHECKING

from ee.models import CoreMemory

if TYPE_CHECKING:
    from posthog.models import Team


class AssistantNodeMixin:
    if TYPE_CHECKING:
        _team: "Team"

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
