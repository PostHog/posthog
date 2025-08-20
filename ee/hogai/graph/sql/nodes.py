from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql.context import HogQLContext
from posthog.schema import AssistantHogQLQuery

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from .mixins import HogQLGeneratorMixin, SQLSchemaGeneratorOutput
from .toolkit import SQL_SCHEMA


class SQLGeneratorNode(HogQLGeneratorMixin, SchemaGeneratorNode[AssistantHogQLQuery]):
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = await self._construct_system_prompt()
        return await super()._run_with_prompt(state, prompt, config=config)


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
