from django.test import SimpleTestCase

from langchain_core.runnables import RunnableConfig

from posthog.models import Team, User

from ee.hogai.core.executable import BaseAgentExecutable
from ee.hogai.utils.types import AssistantState, PartialAssistantState


class Executable(BaseAgentExecutable[AssistantState, PartialAssistantState]):
    pass


class TestExecutableDispatch(SimpleTestCase):
    def _make(self, cls: type[BaseAgentExecutable]) -> BaseAgentExecutable:
        return cls(Team(), User(), ())

    async def test_not_implemented_error_from_arun_propagates(self):
        class Node(Executable):
            async def arun(self, state, config):
                raise NotImplementedError("Unsupported query type: FunnelsQuery")

        with self.assertRaises(NotImplementedError) as ctx:
            await self._make(Node)(AssistantState(messages=[]), RunnableConfig())

        self.assertEqual(str(ctx.exception), "Unsupported query type: FunnelsQuery")

    async def test_sync_only_node_falls_back_to_run(self):
        class Node(Executable):
            def run(self, state, config):
                return PartialAssistantState(messages=[])

        result = await self._make(Node)(AssistantState(messages=[]), RunnableConfig())

        self.assertEqual(result, PartialAssistantState(messages=[]))

    async def test_node_without_implementation_names_the_class(self):
        with self.assertRaises(NotImplementedError) as ctx:
            await self._make(Executable)(AssistantState(messages=[]), RunnableConfig())

        self.assertEqual(str(ctx.exception), "Executable implements neither `arun` nor `run`")
