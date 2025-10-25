from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantHogQLQuery

from posthog.hogql.context import HogQLContext

from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from .mixins import HogQLGeneratorMixin, SQLSchemaGeneratorOutput
from .toolkit import SQL_SCHEMA


class SQLGeneratorNode(HogQLGeneratorMixin, SchemaGeneratorNode[AssistantHogQLQuery]):
    REASONING_MESSAGE = "Creating SQL query"
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.SQL_GENERATOR

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = await self._construct_system_prompt()
        return await super()._run_with_prompt(state, prompt, config=config)


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.SQL_GENERATOR_TOOLS
