import asyncio
from typing import cast

from langchain_core.prompts import ChatPromptTemplate

from posthog.schema import AssistantHogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.direct_connection import resolve_database_for_connection
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
    ResolutionError,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.data_warehouse.backend.models import ExternalDataSource

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
    _user: User
    _database_instance: Database | None = None
    _connection_database_instances: dict[str, Database] | None = None

    def _get_database(self, connection_id: str | None = None) -> Database:
        if not connection_id and self._database_instance:
            return self._database_instance
        if (
            connection_id
            and self._connection_database_instances
            and connection_id in self._connection_database_instances
        ):
            return self._connection_database_instances[connection_id]

        _, database = resolve_database_for_connection(
            self._team,
            connection_id,
            user=self._user,
            error_factory=QueryError,
        )
        if connection_id:
            if self._connection_database_instances is None:
                self._connection_database_instances = {}
            self._connection_database_instances[connection_id] = database
        else:
            self._database_instance = database
        return database

    @database_sync_to_async
    def _aget_database(self, connection_id: str | None = None) -> Database:
        return self._get_database(connection_id)

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(team=self._team, user=self._user, database=database, enable_select_queries=True)
        return hogql_context

    async def _serialize_database_schema(self):
        database = await self._aget_database()
        schema = await serialize_database_schema(database, self._get_default_hogql_context(database))
        direct_connections = await self._aget_direct_query_connections_list()
        if direct_connections:
            return f"{schema}\n\n{direct_connections}"
        return schema

    def _get_direct_query_connections_list(self) -> str:
        sources = (
            ExternalDataSource.objects.filter(
                team_id=self._team.pk,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
            )
            .exclude(deleted=True)
            .order_by("source_type", "prefix", "created_at")
        )

        lines = [
            "Direct query connections available through `connectionId`:",
            "Use these IDs only when the user explicitly asks to query a named warehouse or connection.",
            "",
        ]
        has_sources = False
        for source in sources:
            has_sources = True
            label = source.prefix or source.description or source.connection_id or source.source_type
            lines.append(
                f"- id: {source.id}; name: {label}; source_type: {source.source_type}; "
                f"prefix: {source.prefix or ''}; status: {source.status}; connection_id: {source.connection_id}"
            )

        return "\n".join(lines) if has_sources else ""

    @database_sync_to_async(thread_sensitive=False)
    def _aget_direct_query_connections_list(self) -> str:
        return self._get_direct_query_connections_list()


class HogQLOutputParserMixin(HogQLDatabaseMixin):
    def _parse_output(self, output: dict) -> SQLSchemaGeneratorOutput:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        cleaned_query = result.query.rstrip(";").strip() if result.query else ""
        connection_id = output.get("connectionId")
        return SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query=cleaned_query, connectionId=connection_id),
        )

    def _validate_hogql_query_sync(self, query: str, connection_id: str | None = None) -> AssistantHogQLQuery:
        """
        Validate a HogQL query string and return AssistantHogQLQuery.

        This is the core validation logic used by both internal and external tools.
        """
        cleaned_query = query.rstrip(";").strip() if query else ""
        if not cleaned_query:
            raise PydanticOutputParserException(llm_output="", validation_message="Query is empty")

        try:
            database = self._get_database(connection_id)
            hogql_context = self._get_default_hogql_context(database)
            parsed_query = parse_select(cleaned_query, placeholders={})

            # Replace placeholders with dummy values to compile the generated query.
            finder = find_placeholders(parsed_query)

            # Handle filter placeholders using the proper filter replacement system.
            # Passing None for filters resolves all recognized filter placeholders to True (no-op).
            if finder.has_filters:
                parsed_query = cast(ast.SelectQuery, replace_filters(parsed_query, None, self._team))

            # Handle remaining non-filter placeholders with dummy values.
            if finder.placeholder_fields:
                dummy_placeholders: dict[str, ast.Expr] = {
                    str(field[0]): ast.Constant(value=1) for field in finder.placeholder_fields
                }
                parsed_query = cast(ast.SelectQuery, replace_placeholders(parsed_query, dummy_placeholders))

            prepare_and_print_ast(parsed_query, context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, HogQLNotImplementedError, QueryError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=cleaned_query, validation_message=err_msg)

        return AssistantHogQLQuery(query=cleaned_query, connectionId=connection_id)

    @database_sync_to_async(thread_sensitive=False)
    def _validate_hogql_query(self, query: str, connection_id: str | None = None) -> AssistantHogQLQuery:
        """Async wrapper for _validate_hogql_query_sync."""
        return self._validate_hogql_query_sync(query, connection_id)

    @database_sync_to_async(thread_sensitive=False)
    def _quality_check_output(self, output: SQLSchemaGeneratorOutput):
        query = output.query.query if output.query else None
        if not query:
            raise PydanticOutputParserException(llm_output="", validation_message="Output is empty")
        self._validate_hogql_query_sync(query, output.query.connectionId)


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
