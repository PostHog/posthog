from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.sql.prompts import (
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ..schema_generator.utils import SchemaGeneratorOutput
from .toolkit import SQL_SCHEMA
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql.ai import HOGQL_EXAMPLE_MESSAGE, IDENTITY_MESSAGE, SCHEMA_MESSAGE
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError, NotImplementedError as HogQLNotImplementedError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.schema import AssistantHogQLQuery

SQLSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantHogQLQuery]


class SQLGeneratorNode(SchemaGeneratorNode[AssistantHogQLQuery]):
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        database = create_hogql_database(team=self._team)
        self.hogql_context = HogQLContext(team=self._team, enable_select_queries=True, database=database)
        serialized_database = serialize_database(self.hogql_context)
        schema_description = "\n\n".join(
            (
                f"Table `{table_name}` with fields:\n"
                + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
                for table_name, table in serialized_database.items()
                # Only the most important core tables, plus all warehouse tables
                if table_name in ["events", "groups", "persons"] or table_name in database.get_warehouse_tables()
            )
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", IDENTITY_MESSAGE),
                ("system", f"# Expressions guide\n\n{SQL_EXPRESSIONS_DOCS}"),
                ("system", f"# Supported functions\n\n{SQL_SUPPORTED_FUNCTIONS_DOCS}"),
                ("system", f"# Supported aggregations\n\n{SQL_SUPPORTED_AGGREGATIONS_DOCS}"),
                ("system", f"# Example query\n\n{HOGQL_EXAMPLE_MESSAGE}"),
                ("system", SCHEMA_MESSAGE.format(schema_description=schema_description)),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt(state, prompt, config=config)

    def _parse_output(self, output):  # type: ignore
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        # We also ensure the generated SQL is valid
        assert result.query is not None
        try:
            print_ast(parse_select(result.query), context=self.hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=result.query, validation_message=err_msg)
        return SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=result.query))


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
