from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ChartDisplayType, DataVisualizationNode, HogQLQuery

from posthog.sync import database_sync_to_async

from products.product_analytics.backend.models.insight_variable import InsightVariable

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.sql.mixins import HogQLGeneratorMixin, SQLSchemaGeneratorOutput


class TestSQLMixins(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _get_node(self):
        class DummyNode(HogQLGeneratorMixin):
            pass

        node = DummyNode()
        node._team = self.team
        node._user = self.user
        return node

    @property
    def _node(self):
        return self._get_node()

    def _sql_output(self, query: str) -> SQLSchemaGeneratorOutput:
        return SQLSchemaGeneratorOutput(query=DataVisualizationNode(source=HogQLQuery(query=query)))

    async def test_construct_system_prompt(self):
        mixin = self._node
        prompt_template = await mixin._construct_system_prompt()
        prompt = prompt_template.format()
        self.assertIn("<project_schema>", prompt)
        self.assertIn("Table", prompt)
        self.assertIn("<core_memory>", prompt)
        self.assertIn("system.insight_variables", prompt)
        self.assertIn("FROM system.insight_variables", prompt)

    def test_assert_database_is_cached(self):
        mixin = self._node
        database = mixin._get_database()
        self.assertEqual(mixin._database_instance, database)

    def test_parse_output_success_path(self):
        """Test successful parsing in HogQLGeneratorMixin."""
        mixin = self._node

        # Test direct _parse_output method
        test_output = {"query": "SELECT count() FROM events", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        self.assertIsInstance(result, SQLSchemaGeneratorOutput)
        self.assertEqual(
            result,
            SQLSchemaGeneratorOutput(
                query=DataVisualizationNode(source=HogQLQuery(query="SELECT count() FROM events"))
            ),
        )

    def test_parse_output_with_visualization_settings(self):
        mixin = self._node

        result = mixin._parse_output(
            {
                "query": "SELECT toStartOfDay(timestamp) AS day, count() AS events FROM events GROUP BY day",
                "display": "ActionsLineGraph",
                "x_axis": "day",
                "y_axis": ["events"],
                "series_breakdown_column": None,
                "y_axis_format": "short",
                "y_axis_decimal_places": 0,
                "y_axis_prefix": None,
                "y_axis_suffix": None,
                "show_legend": False,
            }
        )

        self.assertEqual(result.query.display, ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assertEqual(result.query.chartSettings.xAxis.column, "day")
        self.assertEqual(result.query.chartSettings.yAxis[0].column, "events")
        self.assertEqual(result.query.chartSettings.yAxis[0].settings.formatting.style, "short")

    def test_parse_output_with_none_axis_format_omits_empty_formatting(self):
        mixin = self._node

        result = mixin._parse_output(
            {
                "query": "SELECT toStartOfDay(timestamp) AS day, count() AS events FROM events GROUP BY day",
                "display": "ActionsLineGraph",
                "x_axis": "day",
                "y_axis": ["events"],
                "series_breakdown_column": None,
                "y_axis_format": "none",
                "y_axis_decimal_places": None,
                "y_axis_prefix": None,
                "y_axis_suffix": None,
                "show_legend": False,
            }
        )

        self.assertIsNone(result.query.chartSettings.yAxis[0].settings)

    def test_parse_output_with_none_axis_format_preserves_other_formatting(self):
        mixin = self._node

        result = mixin._parse_output(
            {
                "query": "SELECT toStartOfDay(timestamp) AS day, count() AS latency FROM events GROUP BY day",
                "display": "ActionsLineGraph",
                "x_axis": "day",
                "y_axis": ["latency"],
                "series_breakdown_column": None,
                "y_axis_format": "none",
                "y_axis_decimal_places": 2,
                "y_axis_prefix": None,
                "y_axis_suffix": "ms",
                "show_legend": False,
            }
        )

        formatting = result.query.chartSettings.yAxis[0].settings.formatting
        self.assertEqual(formatting.style, "none")
        self.assertEqual(formatting.decimalPlaces, 2)
        self.assertEqual(formatting.suffix, "ms")

    def test_parse_output_with_empty_query(self):
        """Test parsing with empty query string."""
        mixin = self._node

        test_output = {"query": "", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        self.assertIsInstance(result, SQLSchemaGeneratorOutput)
        self.assertEqual(result.query.source.query, "")

    def test_parse_output_removes_semicolon(self):
        """Test that semicolons are removed from the end of queries."""
        mixin = self._node

        test_output = {"query": "SELECT count() FROM events;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        self.assertIsInstance(result, SQLSchemaGeneratorOutput)
        self.assertEqual(result.query.source.query, "SELECT count() FROM events")

    def test_parse_output_removes_multiple_semicolons(self):
        """Test that multiple semicolons are removed from the end of queries."""
        mixin = self._node

        test_output = {"query": "SELECT count() FROM events;;;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        self.assertIsInstance(result, SQLSchemaGeneratorOutput)
        self.assertEqual(result.query.source.query, "SELECT count() FROM events")

    def test_parse_output_preserves_semicolons_in_middle(self):
        """Test that semicolons in the middle of queries are preserved."""
        mixin = self._node

        test_output = {"query": "SELECT 'hello;world' FROM events;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        self.assertIsInstance(result, SQLSchemaGeneratorOutput)
        self.assertEqual(result.query.source.query, "SELECT 'hello;world' FROM events")

    async def test_quality_check_output_success_simple_query(self):
        """Test successful quality check with simple valid query."""
        mixin = self._node

        valid_output = self._sql_output("SELECT count() FROM events")

        # Should not raise any exception for valid SQL
        await mixin._quality_check_output(valid_output)

    async def test_quality_check_output_success_with_placeholders(self):
        """Test successful quality check with placeholders."""
        mixin = self._node

        valid_output = self._sql_output("SELECT properties FROM events WHERE {filters}")

        # Should not raise any exception for valid SQL with placeholders
        await mixin._quality_check_output(valid_output)

    async def test_quality_check_output_invalid_syntax_raises_exception(self):
        """Test quality check failure with an invalid table in the SQL."""
        mixin = self._node

        invalid_output = self._sql_output("SELECT * FROM nowhere")

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_output)

        self.assertEqual(context.exception.llm_output, "SELECT * FROM nowhere")
        self.assertEqual(context.exception.validation_message, "Unknown table `nowhere`.")

    async def test_quality_check_output_empty_query_raises_exception(self):
        """Test quality check failure with empty query."""
        mixin = self._node

        # Create output with None query using model_construct to bypass validation
        empty_output = SQLSchemaGeneratorOutput.model_construct(query=None, name="", description="")  # type: ignore[arg-type]

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(empty_output)

        self.assertEqual(context.exception.llm_output, "")
        self.assertEqual(context.exception.validation_message, "Output is empty")

    async def test_quality_check_output_blank_query_raises_exception(self):
        """Test quality check failure with blank query string."""
        mixin = self._node

        blank_output = self._sql_output("")

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(blank_output)

        self.assertEqual(context.exception.llm_output, "")
        self.assertEqual(context.exception.validation_message, "Output is empty")

    async def test_quality_check_output_no_viable_alternative_error_handling(self):
        """Test that 'no viable alternative' errors get helpful messages."""
        mixin = self._node

        # Create a query that will still trigger the generic "no viable alternative" ANTLR error.
        invalid_syntax_output = self._sql_output("SELECT 1 IS TRUE AS value")

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_syntax_output)

        # Should replace unhelpful ANTLR error with better message
        self.assertEqual(context.exception.llm_output, "SELECT 1 IS TRUE AS value")
        self.assertIn("query isn't valid HogQL", context.exception.validation_message)

    async def test_quality_check_output_nonexistent_table_raises_exception(self):
        """Test quality check failure with nonexistent table."""
        mixin = self._node

        invalid_table_output = self._sql_output("SELECT count() FROM nonexistent_table")

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_table_output)

        self.assertEqual(context.exception.llm_output, "SELECT count() FROM nonexistent_table")
        self.assertEqual(context.exception.validation_message, "Unknown table `nonexistent_table`.")

    async def test_quality_check_output_recursion_error_is_recoverable(self):
        """A deeply nested query that overflows the stack during resolution becomes a recoverable error."""
        mixin = self._node

        output = self._sql_output("SELECT count() FROM events")

        with patch(
            "ee.hogai.chat_agent.sql.mixins.prepare_and_print_ast",
            side_effect=RecursionError,
        ):
            with self.assertRaises(PydanticOutputParserException) as context:
                await mixin._quality_check_output(output)

        self.assertEqual(context.exception.llm_output, "SELECT count() FROM events")
        self.assertIn("too deeply nested", context.exception.validation_message)

    async def test_quality_check_output_complex_query_with_joins(self):
        """Test quality check success with complex query including joins."""
        mixin = self._node

        complex_output = self._sql_output(
            "SELECT e.event, p.id FROM events e LEFT JOIN persons p ON e.person_id = p.id LIMIT 10"
        )

        # Should not raise any exception for valid complex SQL
        await mixin._quality_check_output(complex_output)

    async def test_quality_check_output_success_with_filters_date_range(self):
        mixin = self._node

        valid_output = self._sql_output("SELECT event FROM events WHERE timestamp >= {filters.dateRange.from}")

        await mixin._quality_check_output(valid_output)

    async def test_quality_check_output_with_unsupported_filter_placeholder(self):
        mixin = self._node

        invalid_output = self._sql_output("SELECT dateTrunc({filters.interval}, timestamp) FROM events WHERE {filters}")

        with self.assertRaises(PydanticOutputParserException):
            await mixin._quality_check_output(invalid_output)

    async def test_quality_check_unrecognized_placeholder_reports_clean_error(self):
        mixin = self._node

        output = self._sql_output("SELECT {some_other} AS d FROM events")

        with self.assertRaises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(output)

        self.assertIn("some_other", context.exception.validation_message)

    @parameterized.expand(
        [
            ("resolves_to_default_in_string_context", "SELECT coalesce({variables.district_name}, '') AS d", False),
            ("missing_variable_is_reported", "SELECT {variables.nonexistent} AS d", True),
        ]
    )
    async def test_quality_check_resolves_insight_variables(self, _name: str, query: str, should_raise: bool):
        await database_sync_to_async(InsightVariable.objects.create)(
            team=self.team,
            name="District name",
            code_name="district_name",
            type=InsightVariable.Type.STRING,
            default_value="barbaz",
        )
        mixin = self._node
        output = self._sql_output(query)

        if should_raise:
            with self.assertRaises(PydanticOutputParserException):
                await mixin._quality_check_output(output)
        else:
            await mixin._quality_check_output(output)
