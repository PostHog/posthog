from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.schema_generator.parsers import parse_pydantic_structured_output
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql.context import HogQLContext
from posthog.schema import AssistantHogQLQuery

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .mixins import HogQLGeneratorMixin
from .toolkit import SQL_SCHEMA

SQLSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantHogQLQuery]


class SQLGeneratorNode(HogQLGeneratorMixin, SchemaGeneratorNode[AssistantHogQLQuery]):
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = await self._construct_system_prompt()
        return await super()._run_with_prompt(state, prompt, config=config)

    async def _parse_output(self, output: dict) -> SchemaGeneratorOutput[AssistantHogQLQuery]:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        database = await self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = await self._parse_generated_hogql(result.query, hogql_context)
        return SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=query))


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
