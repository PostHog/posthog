from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ..schema_generator.utils import SchemaGeneratorOutput
from ..taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from .prompts import SQL_REACT_SYSTEM_PROMPT, description_for_table
from .toolkit import SQL_SCHEMA, SQLTaxonomyAgentToolkit
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.hogql.ai import HOGQL_EXAMPLE_MESSAGE, IDENTITY_MESSAGE, SCHEMA_MESSAGE
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database, serialize_database, DatabaseSchemaTable
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.schema import AssistantHogQLQuery
from products.revenue_analytics.backend.views.revenue_analytics_base_view import RevenueAnalyticsBaseView


class SQLPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = SQLTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SQL_REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config=config)


class SQLPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = SQLTaxonomyAgentToolkit(self._team)
        return super()._run_with_toolkit(state, toolkit, config=config)


SQLSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantHogQLQuery]


class SQLGeneratorNode(SchemaGeneratorNode[AssistantHogQLQuery]):
    INSIGHT_NAME = "SQL"
    OUTPUT_MODEL = SQLSchemaGeneratorOutput
    OUTPUT_SCHEMA = SQL_SCHEMA

    hogql_context: HogQLContext

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        database = create_hogql_database(team=self._team)
        self.hogql_context = HogQLContext(team_id=self._team.pk, enable_select_queries=True, database=database)

        serialized_database = serialize_database(self.hogql_context)
        schema_description = "\n\n".join(
            (
                self._schema_description_for_table(table_name, table)
                for table_name, table in serialized_database.items()
                if self._should_include_table_in_schema(table_name, table)
            )
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    IDENTITY_MESSAGE
                    + "\n\n<example_query>\n"
                    + HOGQL_EXAMPLE_MESSAGE
                    + "\n</example_query>\n\n"
                    + SCHEMA_MESSAGE.format(schema_description=schema_description),
                ),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt(state, prompt, config=config)

    def _schema_description_for_table(self, table_name: str, table: DatabaseSchemaTable) -> str:
        # Initial header
        schema_description = f"Table `{table_name}`\n"

        # Optional description extracted from the table
        description = description_for_table(table)
        if description:
            schema_description += f"When to use this table: {description}\n"

        # Each individual field with their type
        schema_description += "Fields:\n"
        schema_description += "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())

        return schema_description

    def _should_include_table_in_schema(self, table_name: str, table: DatabaseSchemaTable) -> bool:
        return (
            table_name in ["events", "groups", "persons"]  # Core relevant tables
            or table_name in self.hogql_context.database.get_warehouse_tables()  # DWH tables are always relevant
            or isinstance(table, RevenueAnalyticsBaseView)  # Include RA views to power revenue-related questions
        )

    def _parse_output(self, output):  # type: ignore
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        # We also ensure the generated SQL is valid
        assert result.query is not None
        try:
            print_ast(parse_select(result.query), context=self.hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = f'This is not valid parsable SQL! The last 5 characters where we tripped up were "{result.query[-5:]}".'
            raise PydanticOutputParserException(llm_output=result.query, validation_message=err_msg)
        return SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=result.query))


class SQLGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
