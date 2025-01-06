from ee.hogai.memory.nodes import MemoryOnboardingNode
from ee.hogai.utils.types import AssistantState
from ee.models import CoreMemory
from posthog.test.base import BaseTest


class TestMemoryOnboardingNode(BaseTest):
    def test_should_run(self):
        node = MemoryOnboardingNode(team=self.team)
        self.assertTrue(node.should_run(AssistantState(messages=[])))

        core_memory = CoreMemory.objects.create(team=self.team)
        self.assertTrue(node.should_run(AssistantState(messages=[])))

        core_memory.change_status_to_pending()
        self.assertFalse(node.should_run(AssistantState(messages=[])))

        core_memory.change_status_to_skipped()
        self.assertFalse(node.should_run(AssistantState(messages=[])))

        core_memory.set_core_memory("Hello World")
        self.assertFalse(node.should_run(AssistantState(messages=[])))
