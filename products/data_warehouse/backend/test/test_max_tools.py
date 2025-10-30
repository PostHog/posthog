from typing import cast

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantHogQLQuery, AssistantToolCall

from products.data_warehouse.backend.max_tools import FinalAnswerArgs, HogQLGeneratorTool

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.graph.sql.mixins import SQLSchemaGeneratorOutput
from ee.hogai.utils.types import AssistantState


class TestDataWarehouseMaxTools(NonAtomicBaseTest):
    async def test_hogql_generator_tool(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        mock_result = {
            "output": FinalAnswerArgs(query="SELECT AVG(properties.$session_length) FROM events"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(
                    query=AssistantHogQLQuery(query="SELECT AVG(properties.$session_length) FROM events")
                ),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What is the average session length?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT AVG(properties.$session_length) FROM events\n```")

    async def test_generates_queries_with_placeholders(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": "SELECT * FROM events WHERE {filters}"}},
            },
        }

        mock_result = {
            "output": FinalAnswerArgs(query="SELECT properties FROM events WHERE {filters} AND {custom_filter}"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(
                    query=AssistantHogQLQuery(query="SELECT properties FROM events WHERE {filters} AND {custom_filter}")
                ),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What are the properties for the variable {filters}?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(
                result.content, "```sql\nSELECT properties FROM events WHERE {filters} AND {custom_filter}\n```"
            )

    async def test_hogql_tool_quality_check_integration(self):
        """Test that HogQLGeneratorTool properly calls quality check methods."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(HogQLGeneratorTool, "_quality_check_output") as mock_quality_check,
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {
                "output": FinalAnswerArgs(query="SELECT count() FROM events"),
                "intermediate_steps": None,
            }

            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )

            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))

            # Should succeed
            self.assertEqual(result.content, "```sql\nSELECT count() FROM events\n```")
            # Quality check should have been called exactly once (happy path, loop breaks on success)
            mock_quality_check.assert_called_once()
            # Graph should have been called exactly once (happy path, loop breaks on success)
            mock_graph.ainvoke.assert_called_once()
            # Verify it was called with the expected SQL query
            call_args = mock_quality_check.call_args.kwargs["output"]
            self.assertEqual(call_args.query.query, "SELECT count() FROM events")

    async def test_hogql_tool_retry_exhausted_still_returns_result(self):
        """Test HogQLGeneratorTool behavior when retries are exhausted but we have a valid parsed result."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        # Mock the graph to return same result that fails quality check every time
        mock_result = {
            "output": FinalAnswerArgs(query="SELECT suspicious_query FROM events"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(HogQLGeneratorTool, "_quality_check_output") as mock_quality_check,
            patch("products.data_warehouse.backend.max_tools.capture_exception") as mock_capture,
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            # Quality check always fails
            mock_quality_check.side_effect = PydanticOutputParserException(
                "SELECT suspicious_query FROM events", "Suspicious query detected"
            )

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )

            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))

            # Should still return the result despite quality check failure
            self.assertEqual(result.content, "```sql\nSELECT suspicious_query FROM events\n```")
            # Should have tried 3 times (GENERATION_ATTEMPTS_ALLOWED = 3)
            self.assertEqual(mock_quality_check.call_count, 3)
            # Should capture the exception
            mock_capture.assert_called_once()

            # Verify that error feedback was incorporated in retry attempts
            # The graph should be called 3 times, with error messages appended after failures
            self.assertEqual(mock_graph.ainvoke.call_count, 3)

            # Check that the second call includes the error message from the first failure
            second_call_context = mock_graph.ainvoke.call_args_list[1][0][0]
            self.assertIn("Suspicious query detected", second_call_context["change"])

            # Check that the third call includes error messages from previous failures
            third_call_context = mock_graph.ainvoke.call_args_list[2][0][0]
            self.assertIn("Suspicious query detected", third_call_context["change"])

    async def test_hogql_tool_no_valid_result_raises_exception(self):
        """Test HogQLGeneratorTool behavior when no valid result is ever produced."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        # Mock the graph to return no output
        mock_result = {
            "output": None,
            "intermediate_steps": None,
        }

        with patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile:
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )

            # Should raise an exception when no valid result is produced
            with self.assertRaises(Exception):
                await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))

    async def test_hogql_tool_removes_semicolon_from_query(self):
        """Test that HogQLGeneratorTool properly removes semicolons from the end of queries."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        graph_result = {
            "output": FinalAnswerArgs(query="SELECT count() FROM events;"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch("ee.hogai.graph.sql.mixins.parse_pydantic_structured_output") as mock_parse,
        ):
            mock_parse_result = Mock()
            mock_parse_result.query = "SELECT count() FROM events;"
            mock_parse.return_value = lambda x: mock_parse_result
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = graph_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT count() FROM events\n```")

    async def test_hogql_tool_removes_multiple_semicolons_from_query(self):
        """Test that HogQLGeneratorTool properly removes multiple semicolons from the end of queries."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        graph_result = {
            "output": FinalAnswerArgs(query="SELECT count() FROM events;;;"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch("ee.hogai.graph.sql.mixins.parse_pydantic_structured_output") as mock_parse,
        ):
            mock_parse_result = Mock()
            mock_parse_result.query = "SELECT count() FROM events;;;"
            mock_parse.return_value = lambda x: mock_parse_result
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = graph_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT count() FROM events\n```")

    async def test_hogql_tool_preserves_semicolons_in_middle_of_query(self):
        """Test that HogQLGeneratorTool preserves semicolons in the middle of queries."""
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        graph_result = {
            "output": FinalAnswerArgs(query="SELECT 'hello;world' FROM events;"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch("ee.hogai.graph.sql.mixins.parse_pydantic_structured_output") as mock_parse,
        ):
            mock_parse_result = Mock()
            mock_parse_result.query = "SELECT 'hello;world' FROM events;"
            mock_parse.return_value = lambda x: mock_parse_result
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = graph_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(
                team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
            )
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Get hello world"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT 'hello;world' FROM events\n```")

    def test_current_query_included_in_system_prompt_template(self):
        """Test that the system prompt template includes the current query section."""
        tool = HogQLGeneratorTool(
            team=self.team, user=self.user, state=AssistantState(messages=[]), tool_call_id="test-tool-call-id"
        )

        # Verify the system prompt template contains the expected current query section
        self.assertIn("The current HogQL query", tool.context_prompt_template)
        self.assertIn("<current_query>", tool.context_prompt_template)
        self.assertIn("{current_query}", tool.context_prompt_template)
        self.assertIn("</current_query>", tool.context_prompt_template)
