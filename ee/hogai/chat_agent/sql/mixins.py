import asyncio
from typing import cast

from langchain_core.prompts import ChatPromptTemplate

from posthog.schema import AssistantHogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    ResolutionError,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import Team
from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.warehouse import serialize_database_schema

from ..schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from .prompts import (
    HOGQL_GENERATOR_SYSTEM_PROMPT,
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)

SQLSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantHogQLQuery]


class HogQLDatabaseMixin:
    _team: Team
    _database_instance: Database | None = None

    def _get_database(self):
        if self._database_instance:
            return self._database_instance
        self._database_instance = Database.create_for(team=self._team)
        return self._database_instance

    @database_sync_to_async
    def _aget_database(self):
        return self._get_database()

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(team=self._team, database=database, enable_select_queries=True)
        return hogql_context

    async def _serialize_database_schema(self):
        database = await self._aget_database()
        return await serialize_database_schema(database, self._get_default_hogql_context(database))


class HogQLOutputParserMixin(HogQLDatabaseMixin):
    def _parse_output(self, output: dict) -> SQLSchemaGeneratorOutput:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        cleaned_query = result.query.rstrip(";").strip() if result.query else ""
        return SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query=cleaned_query),
        )

    def _validate_hogql_query_sync(self, query: str) -> AssistantHogQLQuery:
        """
        Validate a HogQL query string and return AssistantHogQLQuery.

        This is the core validation logic used by both internal and external tools.
        """
        cleaned_query = query.rstrip(";").strip() if query else ""
        if not cleaned_query:
            raise PydanticOutputParserException(llm_output="", validation_message="Query is empty")

        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        try:
            parsed_query = parse_select(cleaned_query, placeholders={})

            # Replace placeholders with dummy values to compile the generated query.
            finder = find_placeholders(parsed_query)
            if finder.placeholder_fields or finder.has_filters:
                dummy_placeholders: dict[str, ast.Expr] = {
                    str(field[0]): ast.Constant(value=1) for field in finder.placeholder_fields
                }
                if finder.has_filters:
                    dummy_placeholders["filters"] = ast.Constant(value=1)
                parsed_query = cast(ast.SelectQuery, replace_placeholders(parsed_query, dummy_placeholders))

            prepare_and_print_ast(parsed_query, context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=cleaned_query, validation_message=err_msg)

        return AssistantHogQLQuery(query=cleaned_query)

    @database_sync_to_async(thread_sensitive=False)
    def _validate_hogql_query(self, query: str) -> AssistantHogQLQuery:
        """Async wrapper for _validate_hogql_query_sync."""
        return self._validate_hogql_query_sync(query)

    @database_sync_to_async(thread_sensitive=False)
    def _quality_check_output(self, output: SQLSchemaGeneratorOutput):
        query = output.query.query if output.query else None
        if not query:
            raise PydanticOutputParserException(llm_output="", validation_message="Output is empty")
        self._validate_hogql_query_sync(query)


class HogQLGeneratorMixin(HogQLOutputParserMixin, AssistantContextMixin):
    async def _construct_system_prompt(self) -> ChatPromptTemplate:
        schema_description, core_memory = await asyncio.gather(
            self._serialize_database_schema(),
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
