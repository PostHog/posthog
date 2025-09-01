import asyncio

from langchain_core.prompts import ChatPromptTemplate

from posthog.schema import AssistantHogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    ResolutionError,
)
from posthog.hogql.functions.mapping import find_function_name_case_insensitive
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast, print_prepared_ast
from posthog.hogql.visitor import CloningVisitor

from posthog.sync import database_sync_to_async

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.utils.warehouse import serialize_database_schema

from ..schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from .prompts import (
    HOGQL_GENERATOR_SYSTEM_PROMPT,
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)

SQLSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantHogQLQuery]


class LooseSyntaxVisitor(CloningVisitor):
    """
    Syntax guardrails for Max-generated SQL queries.
    """

    def visit_call(self, node: ast.Call):
        """Convert case-insensitive function names to case-sensitive ones."""
        corrected_name = find_function_name_case_insensitive(node.name)
        if corrected_name != node.name:
            node.name = corrected_name
        return super().visit_call(node)


class HogQLGeneratorMixin(AssistantContextMixin):
    _database_instance: Database | None = None

    def _get_database(self):
        if self._database_instance:
            return self._database_instance
        self._database_instance = create_hogql_database(team=self._team)
        return self._database_instance

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(
            team=self._team,
            database=database,
            enable_select_queries=True,
            limit_top_select=False,
            readable_print=True,
            keep_placeholders=True,
        )
        return hogql_context

    async def _construct_system_prompt(self) -> ChatPromptTemplate:
        database = await database_sync_to_async(self._get_database)()
        hogql_context = self._get_default_hogql_context(database)

        schema_description, core_memory = await asyncio.gather(
            serialize_database_schema(database, hogql_context),
            self._aget_core_memory_text(),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", HOGQL_GENERATOR_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).partial(
            sql_expressions_docs=SQL_EXPRESSIONS_DOCS,
            sql_supported_functions_docs=SQL_SUPPORTED_FUNCTIONS_DOCS,
            sql_supported_aggregations_docs=SQL_SUPPORTED_AGGREGATIONS_DOCS,
            schema_description=schema_description,
            core_memory=core_memory,
        )

        return prompt

    def _parse_output(self, output: dict) -> SQLSchemaGeneratorOutput:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        cleaned_query = result.query.rstrip(";").strip() if result.query else ""
        return SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=cleaned_query))

    @database_sync_to_async(thread_sensitive=False)
    def _quality_check_output(self, output: SQLSchemaGeneratorOutput):
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = output.query.query if output.query else None
        if not query:
            raise PydanticOutputParserException(llm_output="", validation_message="Output is empty")
        try:
            # First pass to fix the query syntax
            fixed_names_query = LooseSyntaxVisitor().visit(parse_select(query, placeholders={}))
            normalized_query = print_prepared_ast(
                fixed_names_query, context=hogql_context, dialect="hogql", pretty=True
            )

            # Validate that the query is valid
            print_ast(fixed_names_query, context=hogql_context, dialect="hogql")
            # Return the normalized query
            return normalized_query
        except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=query, validation_message=err_msg)
