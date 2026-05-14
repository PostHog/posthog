from posthog.test.base import APIBaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from products.data_warehouse.backend.hogql_expression_ai import HogQLExpressionWriterTool

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.registry import get_contextual_tool_class


class TestHogQLExpressionWriterTool(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.tool = HogQLExpressionWriterTool(team=self.team, user=self.user)
        database = Database.create_for(team=self.team, user=self.user)
        self.hogql_context = HogQLContext(team=self.team, user=self.user, enable_select_queries=True, database=database)

    def test_tool_is_registered_with_assistant_tool_enum(self) -> None:
        tool_class = get_contextual_tool_class("write_hogql_expression")
        assert tool_class is HogQLExpressionWriterTool

    def test_parse_output_accepts_a_simple_property_access_expression(self) -> None:
        assert (
            self.tool._parse_output({"expression": "properties.$current_url"}, self.hogql_context)
            == "properties.$current_url"
        )

    def test_parse_output_strips_trailing_semicolons_and_whitespace(self) -> None:
        assert self.tool._parse_output({"expression": "  toInt(properties.foo) * 10;  "}, self.hogql_context) == (
            "toInt(properties.foo) * 10"
        )

    def test_parse_output_accepts_trailing_as_alias(self) -> None:
        assert (
            self.tool._parse_output({"expression": "properties.$browser AS browser"}, self.hogql_context)
            == "properties.$browser AS browser"
        )

    def test_parse_output_accepts_trailing_comment_label(self) -> None:
        assert (
            self.tool._parse_output({"expression": "properties.$browser -- browser"}, self.hogql_context)
            == "properties.$browser -- browser"
        )

    def test_parse_output_rejects_empty_expression(self) -> None:
        with self.assertRaises(PydanticOutputParserException) as ctx:
            self.tool._parse_output({"expression": "   "}, self.hogql_context)
        assert "empty" in str(ctx.exception.validation_message).lower()

    def test_parse_output_rejects_invalid_expression(self) -> None:
        with self.assertRaises(PydanticOutputParserException):
            self.tool._parse_output({"expression": "this is !!!not valid hogql"}, self.hogql_context)

    def test_parse_output_rejects_select_statement(self) -> None:
        with self.assertRaises(PydanticOutputParserException):
            self.tool._parse_output({"expression": "SELECT * FROM events"}, self.hogql_context)
