from ee.models import CoreMemory
from posthog.models import Team


class AssistantNodeMixin:
    async def _aget_core_memory(self, team: Team) -> CoreMemory | None:
        try:
            return await CoreMemory.objects.aget(team=team)
        except CoreMemory.DoesNotExist:
            return None

    async def _aget_core_memory_text(self, team: Team) -> str:
        core_memory = await self._aget_core_memory(team)
        if not core_memory:
            return ""
        return core_memory.formatted_text
