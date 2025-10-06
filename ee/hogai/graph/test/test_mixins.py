from posthog.test.base import BaseTest

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.models.assistant import CoreMemory


class TestAssistantNodeMixin(BaseTest):
    def setUp(self):
        super().setUp()

        class TestNode(AssistantContextMixin):
            def __init__(self, team, user):
                self._team = team
                self._user = user

        self.node = TestNode(self.team, self.user)

    async def test_aget_core_memory_when_exists(self):
        core_memory = await CoreMemory.objects.acreate(team=self.team, text="Test memory")
        result = await self.node._aget_core_memory()
        self.assertEqual(result, core_memory)

    async def test_aget_core_memory_when_does_not_exist(self):
        result = await self.node._aget_core_memory()
        self.assertIsNone(result)

    async def test_aget_core_memory_text_when_exists(self):
        await CoreMemory.objects.acreate(team=self.team, text="Test memory content")
        result = await self.node._aget_core_memory_text()
        self.assertEqual(result, "Test memory content")
