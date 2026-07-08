import asyncio
from typing import cast

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import (
    AssistantHogQLQuery,
    ChartAxis,
    ChartDisplayType,
    ChartSettings,
    ChartSettingsFormatting,
    DataVisualizationNode,
    HogQLQuery,
    HogQLVariable,
    Settings,
    Style,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
    ResolutionError,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.variables import replace_variables

from posthog.models import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.product_analytics.backend.models.insight_variable import InsightVariable

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


class RawSQLSchemaGeneratorOutput(BaseModel):
    query: str
    display: ChartDisplayType | None = None
    x_axis: str | None = None
    y_axis: list[str] = Field(default_factory=list)
    series_breakdown_column: str | None = None
    y_axis_format: Style | None = None
    y_axis_decimal_places: int | None = None
    y_axis_prefix: str | None = None
    y_axis_suffix: str | None = None
    show_legend: bool | None = None


SQLSchemaGeneratorOutput = SchemaGeneratorOutput[DataVisualizationNode]


class HogQLDatabaseMixin:
    _team: Team
    _user: User
    _database_instance: Database | None = None

    def _get_database(self):
        if self._database_instance:
            return self._database_instance
        self._database_instance = Database.create_for(team=self._team, user=self._user)
        return self._database_instance

    @database_sync_to_async
    def _aget_database(self):
        return self._get_database()

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(team=self._team, user=self._user, database=database, enable_select_queries=True)
        return hogql_context

    async def _serialize_database_schema(self):
        database = await self._aget_database()
        return await serialize_database_schema(database, self._get_default_hogql_context(database))


class HogQLOutputParserMixin(HogQLDatabaseMixin):
    def _parse_output(self, output: dict) -> SQLSchemaGeneratorOutput:
        result = parse_pydantic_structured_output(RawSQLSchemaGeneratorOutput)(output)
        cleaned_query = result.query.rstrip(";").strip() if result.query else ""

        formatting = self._build_axis_formatting(result)
        y_axis = [
            ChartAxis(
                column=column,
                settings=Settings(formatting=formatting) if formatting else None,
            )
            for column in result.y_axis
        ]

        chart_settings = None
        if result.display not in (None, ChartDisplayType.ACTIONS_TABLE, ChartDisplayType.BOLD_NUMBER):
            chart_settings = ChartSettings(
                xAxis=ChartAxis(column=result.x_axis) if result.x_axis else None,
                yAxis=y_axis or None,
                seriesBreakdownColumn=result.series_breakdown_column,
                showLegend=result.show_legend,
            )

        return SQLSchemaGeneratorOutput(
            query=DataVisualizationNode(
                source=HogQLQuery(query=cleaned_query),
                display=result.display,
                chartSettings=chart_settings,
            ),
        )

    def _build_axis_formatting(self, result: RawSQLSchemaGeneratorOutput) -> ChartSettingsFormatting | None:
        has_formatting = (
            result.y_axis_format not in (None, Style.NONE)
            or result.y_axis_decimal_places is not None
            or bool(result.y_axis_prefix)
            or bool(result.y_axis_suffix)
        )
        if not has_formatting:
            return None
        return ChartSettingsFormatting(
            style=result.y_axis_format,
            decimalPlaces=result.y_axis_decimal_places,
            prefix=result.y_axis_prefix,
            suffix=result.y_axis_suffix,
        )

    def _get_insight_variables(self, placeholder_fields: list[list[str | int]]) -> list[HogQLVariable]:
        code_names = {str(chain[1]) for chain in placeholder_fields if len(chain) >= 2 and chain[0] == "variables"}
        if not code_names:
            return []
        insight_variables = InsightVariable.objects.filter(team_id=self._team.pk, code_name__in=code_names)
        return [
            HogQLVariable(variableId=str(variable.id), code_name=variable.code_name)
            for variable in insight_variables
            if variable.code_name
        ]

    def _build_query_variables(self, query: str) -> dict[str, HogQLVariable]:
        parsed_query = parse_select(query, placeholders={})
        finder = find_placeholders(parsed_query)
        return {variable.variableId: variable for variable in self._get_insight_variables(finder.placeholder_fields)}

    @database_sync_to_async
    def _abuild_query_variables(self, query: str) -> dict[str, HogQLVariable]:
        return self._build_query_variables(query)

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

            finder = find_placeholders(parsed_query)

            # Handle filter placeholders using the proper filter replacement system.
            # Passing None for filters resolves all recognized filter placeholders to True (no-op).
            if finder.has_filters:
                parsed_query = cast(ast.SelectQuery, replace_filters(parsed_query, None, self._team))

            if any(field and field[0] == "variables" for field in finder.placeholder_fields):
                variables = self._get_insight_variables(finder.placeholder_fields)
                parsed_query = cast(ast.SelectQuery, replace_variables(parsed_query, variables, self._team))

            prepare_and_print_ast(parsed_query, context=hogql_context, dialect="clickhouse")
        except RecursionError:
            # Parsing/resolving walks the AST via the visitor pattern, so a deeply nested query can
            # blow past Python's recursion limit. Surface it as a recoverable error the agent can act
            # on instead of letting it escape to the generic error handler.
            raise PydanticOutputParserException(
                llm_output=cleaned_query,
                validation_message="HogQL parsing error: this query is too deeply nested. Simplify it by reducing the levels of nested subqueries, expressions, or parentheses.",
            )
        except (ExposedHogQLError, HogQLNotImplementedError, QueryError, ResolutionError) as err:
            err_msg = str(err)
            # Both the antlr-based cpp parser and the hand-rolled rust-py parser produce
            # terse low-level error wording on syntax failures ("no viable alternative…",
            # "trailing tokens after expression…", "unexpected token in expression…",
            # "mismatched input … expecting …"). Replace any of them with a single
            # human/LLM-friendly message.
            if err_msg.startswith(
                (
                    "no viable alternative",
                    "trailing tokens after expression",
                    "unexpected token in expression",
                    "mismatched input",
                )
            ):
                err_msg = "HogQL parsing error: this query isn't valid HogQL."
            raise PydanticOutputParserException(llm_output=cleaned_query, validation_message=err_msg)

        return AssistantHogQLQuery(query=cleaned_query)

    @database_sync_to_async(thread_sensitive=False)
    def _validate_hogql_query(self, query: str) -> AssistantHogQLQuery:
        """Async wrapper for _validate_hogql_query_sync."""
        return self._validate_hogql_query_sync(query)

    @database_sync_to_async(thread_sensitive=False)
    def _quality_check_output(self, output: SQLSchemaGeneratorOutput):
        query = output.query.source.query if output.query else None
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
