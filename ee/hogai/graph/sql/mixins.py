import asyncio
from typing import cast

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
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import print_ast

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


class HogQLGeneratorMixin(AssistantContextMixin):
    _database_instance: Database | None = None

    def _get_database(self):
        if self._database_instance:
            return self._database_instance
        self._database_instance = create_hogql_database(team=self._team)
        return self._database_instance

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(team=self._team, database=database, enable_select_queries=True)
        return hogql_context

    async def _construct_system_prompt(self, absolute_sql_dates: bool = False) -> ChatPromptTemplate:
        database = await database_sync_to_async(self._get_database)()
        hogql_context = self._get_default_hogql_context(database)

        schema_description, core_memory = await asyncio.gather(
            serialize_database_schema(database, hogql_context),
            self._aget_core_memory_text(),
        )

        partial_kwargs = {
            "sql_expressions_docs": SQL_EXPRESSIONS_DOCS,
            "sql_supported_functions_docs": SQL_SUPPORTED_FUNCTIONS_DOCS,
            "sql_supported_aggregations_docs": SQL_SUPPORTED_AGGREGATIONS_DOCS,
            "schema_description": schema_description,
            "core_memory": core_memory,
            # Forcing absolute dates in SQL generation (e.g. for Deep Research reports generation)
            "absolute_sql_dates_section": self._get_absolute_sql_dates_section() if absolute_sql_dates else "",
        }

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", HOGQL_GENERATOR_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).partial(**partial_kwargs)

        return prompt

    def _parse_output(self, output: dict) -> SQLSchemaGeneratorOutput:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        cleaned_query = result.query.rstrip(";").strip() if result.query else ""
        return SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=cleaned_query))

    def _get_absolute_sql_dates_section(self) -> str:
        return """<sql_dates_policy>
- Do NOT use relative functions: now(), now64(), today(), yesterday(), tomorrow(),
  dateAdd/dateSub, addDays/addHours/... subtractDays/subtractHours/..., INTERVAL arithmetic.
- Replace them with absolute literals
  Emit:
    - dates:     toDate('YYYY-MM-DD')
    - datetimes: toDateTime('YYYY-MM-DD HH:MM:SS')
- If the prompt implies windows relative to now (e.g. "last 7 days", "this month"), compute bounds
  from current time and emit **constants only**. Examples:
    - toStartOfWeek(now())            -> toDate('YYYY-MM-DD')      # Monday 00:00
    - toStartOfMonth(now())           -> toDate('YYYY-MM-01')
    - now() - INTERVAL 7 DAY          -> toDateTime('YYYY-MM-DD HH:MM:SS')
    - addHours(now(), 2)              -> toDateTime('YYYY-MM-DD HH:MM:SS')
- If a start-of-* function is used, compute it first, then freeze it:
    - toStartOfWeek(now()) - INTERVAL 8 WEEK
      -> toDate('YYYY-MM-DD') where date = start_of_week(current_time) - 8 weeks
- Keep semantics identical to the relative form (week starts Monday; midnight for date-only).
</sql_dates_policy>
"""

    @database_sync_to_async(thread_sensitive=False)
    def _quality_check_output(self, output: SQLSchemaGeneratorOutput):
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = output.query.query if output.query else None
        if not query:
            raise PydanticOutputParserException(llm_output="", validation_message="Output is empty")
        try:
            parsed_query = parse_select(query, placeholders={})

            # Replace placeholders with dummy values to compile the generated query.
            finder = find_placeholders(parsed_query)
            if finder.placeholder_fields or finder.has_filters:
                dummy_placeholders: dict[str, ast.Expr] = {
                    str(field[0]): ast.Constant(value=1) for field in finder.placeholder_fields
                }
                if finder.has_filters:
                    dummy_placeholders["filters"] = ast.Constant(value=1)
                parsed_query = cast(ast.SelectQuery, replace_placeholders(parsed_query, dummy_placeholders))

            print_ast(parsed_query, context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=query, validation_message=err_msg)
