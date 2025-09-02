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
            "output": FinalAnswerArgs(query="SELECT avg(properties.$session_length) FROM events"),
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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What is the average session length?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(
                result.content, "```sql\nSELECT\n    avg(properties.$session_length)\nFROM\n    events\n```"
            )

    async def test_hogql_tool_generates_queries_with_pretty_print(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        mock_result = {
            "output": FinalAnswerArgs(query="SELECT 30 + 20"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query="SELECT 30 + 20")),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What is 30 + 20?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(
                result.content,
                "```sql\nSELECT\n    30 + 20\n```",
            )

    async def test_hogql_tool_generates_queries_with_pretty_print_and_cte(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {"generate_hogql_query": {"current_query": ""}},
            },
        }

        mock_result = {
            "output": FinalAnswerArgs(query="WITH count() AS kokk SELECT kokk FROM events"),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(
                    query=AssistantHogQLQuery(query="WITH count() AS kokk SELECT kokk FROM events")
                ),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What is the average session length?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(
                result.content, "```sql\nWITH\n    count() AS kokk\nSELECT\n    kokk\nFROM\n    events\n```"
            )

    async def test_hogql_tool_generates_queries_with_placeholders(self):
        config = {
            "configurable": {
                "team": self.team,
                "user": self.user,
                "contextual_tools": {
                    "generate_hogql_query": {"current_query": "SELECT * FROM events WHERE length({filters}) > 0"}
                },
            },
        }

        mock_result = {
            "output": FinalAnswerArgs(
                query="SELECT properties FROM events WHERE length({filters}) > 0 AND {custom_filter} OR {custom_filter_3} ORDER BY properties.$os ASC"
            ),
            "intermediate_steps": None,
        }

        with (
            patch("products.data_warehouse.backend.max_tools.HogQLGeneratorGraph.compile_full_graph") as mock_compile,
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(
                    query=AssistantHogQLQuery(
                        query="SELECT properties FROM events WHERE TOSTRING(properties.$os) = 'Mac OS' AND length({filters}) > 0 AND {custom_filter} OR {custom_filter_3} ORDER BY properties.$os ASC"
                    )
                ),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = mock_result
            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "What are the properties for the variable {filters}?"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(
                result.content,
                "```sql\nSELECT\n    properties\nFROM\n    events\nWHERE\n    toString(properties.$os) = 'Mac OS' AND length({filters}) > 0 AND {custom_filter} OR {custom_filter_3}\nORDER BY\n    properties.$os ASC\n```",
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
            patch.object(
                HogQLGeneratorTool,
                "_parse_output",
                return_value=SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query="SELECT count() FROM events")),
            ),
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.return_value = {
                "output": FinalAnswerArgs(query="SELECT count() FROM events"),
                "intermediate_steps": None,
            }

            mock_compile.return_value = mock_graph

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )

            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))

            # Should succeed
            self.assertEqual(result.content, "```sql\nSELECT\n    count()\nFROM\n    events\n```")
            # Quality check should have been called exactly once (happy path, loop breaks on success)
            # Graph should have been called exactly once (happy path, loop breaks on success)
            mock_graph.ainvoke.assert_called_once()

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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT\n    count()\nFROM\n    events\n```")

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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Count events"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT\n    count()\nFROM\n    events\n```")

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

            tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))
            tool_call = AssistantToolCall(
                id="1",
                name="generate_hogql_query",
                type="tool_call",
                args={"instructions": "Get hello world"},
            )
            result = await tool.ainvoke(tool_call.model_dump(), config=cast(RunnableConfig, config))
            self.assertEqual(result.content, "```sql\nSELECT\n    'hello;world'\nFROM\n    events\n```")

    def test_current_query_included_in_system_prompt_template(self):
        """Test that the system prompt template includes the current query section."""
        tool = HogQLGeneratorTool(team=self.team, user=self.user, state=AssistantState(messages=[]))

        # Verify the system prompt template contains the expected current query section
        self.assertIn("The current HogQL query", tool.root_system_prompt_template)
        self.assertIn("<current_query>", tool.root_system_prompt_template)
        self.assertIn("{current_query}", tool.root_system_prompt_template)
        self.assertIn("</current_query>", tool.root_system_prompt_template)
