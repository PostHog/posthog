from posthog.test.base import BaseTest

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName
from ee.models.assistant import CoreMemory


class TestAssistantNode(BaseTest):
    def setUp(self):
        super().setUp()

        class Node(AssistantNode):
            def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
                raise NotImplementedError

            @property
            def node_name(self) -> MaxNodeName:
                return AssistantNodeName.ROOT

        self.node = Node(self.team, self.user)

    def test_core_memory_when_exists(self):
        core_memory = CoreMemory.objects.create(team=self.team, text="Test memory")
        self.assertEqual(self.node.core_memory, core_memory)

    def test_core_memory_when_does_not_exist(self):
        self.assertIsNone(self.node.core_memory)

    def test_product_core_memory_when_exists(self):
        CoreMemory.objects.create(team=self.team, text="Test memory")
        self.assertEqual(self.node.core_memory_text, "Test memory")

    def test_product_core_memory_when_does_not_exist(self):
        self.assertEqual(self.node.core_memory_text, "")
