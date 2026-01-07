from posthog.test.base import NonAtomicBaseTest

from posthog.schema import AssistantHogQLQuery

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.sql.mixins import HogQLGeneratorMixin, SQLSchemaGeneratorOutput
import pytest


class TestSQLMixins(NonAtomicBaseTest):
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

    async def test_construct_system_prompt(self):
        mixin = self._node
        prompt_template = await mixin._construct_system_prompt()
        prompt = prompt_template.format()
        assert "<project_schema>" in prompt
        assert "Table" in prompt
        assert "<core_memory>" in prompt

    def test_assert_database_is_cached(self):
        mixin = self._node
        database = mixin._get_database()
        assert mixin._database_instance == database

    def test_parse_output_success_path(self):
        """Test successful parsing in HogQLGeneratorMixin."""
        mixin = self._node

        # Test direct _parse_output method
        test_output = {"query": "SELECT count() FROM events", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        assert isinstance(result, SQLSchemaGeneratorOutput)
        assert result == SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query="SELECT count() FROM events"), name="", description="")

    def test_parse_output_with_empty_query(self):
        """Test parsing with empty query string."""
        mixin = self._node

        test_output = {"query": "", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        assert isinstance(result, SQLSchemaGeneratorOutput)
        assert result.query.query == ""

    def test_parse_output_removes_semicolon(self):
        """Test that semicolons are removed from the end of queries."""
        mixin = self._node

        test_output = {"query": "SELECT count() FROM events;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        assert isinstance(result, SQLSchemaGeneratorOutput)
        assert result.query.query == "SELECT count() FROM events"

    def test_parse_output_removes_multiple_semicolons(self):
        """Test that multiple semicolons are removed from the end of queries."""
        mixin = self._node

        test_output = {"query": "SELECT count() FROM events;;;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        assert isinstance(result, SQLSchemaGeneratorOutput)
        assert result.query.query == "SELECT count() FROM events"

    def test_parse_output_preserves_semicolons_in_middle(self):
        """Test that semicolons in the middle of queries are preserved."""
        mixin = self._node

        test_output = {"query": "SELECT 'hello;world' FROM events;", "name": "", "description": ""}
        result = mixin._parse_output(test_output)

        assert isinstance(result, SQLSchemaGeneratorOutput)
        assert result.query.query == "SELECT 'hello;world' FROM events"

    async def test_quality_check_output_success_simple_query(self):
        """Test successful quality check with simple valid query."""
        mixin = self._node

        valid_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query="SELECT count() FROM events"), name="", description=""
        )

        # Should not raise any exception for valid SQL
        await mixin._quality_check_output(valid_output)

    async def test_quality_check_output_success_with_placeholders(self):
        """Test successful quality check with placeholders."""
        mixin = self._node

        valid_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query="SELECT properties FROM events WHERE {filters}"), name="", description=""
        )

        # Should not raise any exception for valid SQL with placeholders
        await mixin._quality_check_output(valid_output)

    async def test_quality_check_output_invalid_syntax_raises_exception(self):
        """Test quality check failure with an invalid table in the SQL."""
        mixin = self._node

        invalid_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query="SELECT * FROM nowhere"), name="", description=""
        )

        with pytest.raises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_output)

        assert context.value.llm_output == "SELECT * FROM nowhere"
        assert context.value.validation_message == "Unknown table `nowhere`."

    async def test_quality_check_output_empty_query_raises_exception(self):
        """Test quality check failure with empty query."""
        mixin = self._node

        # Create output with None query using model_construct to bypass validation
        empty_output = SQLSchemaGeneratorOutput.model_construct(query=None, name="", description="")  # type: ignore[arg-type]

        with pytest.raises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(empty_output)

        assert context.value.llm_output == ""
        assert context.value.validation_message == "Output is empty"

    async def test_quality_check_output_blank_query_raises_exception(self):
        """Test quality check failure with blank query string."""
        mixin = self._node

        blank_output = SQLSchemaGeneratorOutput(query=AssistantHogQLQuery(query=""), name="", description="")

        with pytest.raises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(blank_output)

        assert context.value.llm_output == ""
        assert context.value.validation_message == "Output is empty"

    async def test_quality_check_output_no_viable_alternative_error_handling(self):
        """Test that 'no viable alternative' errors get helpful messages."""
        mixin = self._node

        # Create a query that will trigger the "no viable alternative" ANTLR error
        invalid_syntax_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query="SELECT FROM events"),
            name="",
            description="",  # Missing column
        )

        with pytest.raises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_syntax_output)

        # Should replace unhelpful ANTLR error with better message
        assert context.value.llm_output == "SELECT FROM events"
        assert "query isn't valid HogQL" in context.value.validation_message

    async def test_quality_check_output_nonexistent_table_raises_exception(self):
        """Test quality check failure with nonexistent table."""
        mixin = self._node

        invalid_table_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(query="SELECT count() FROM nonexistent_table"), name="", description=""
        )

        with pytest.raises(PydanticOutputParserException) as context:
            await mixin._quality_check_output(invalid_table_output)

        assert context.value.llm_output == "SELECT count() FROM nonexistent_table"
        assert context.value.validation_message == "Unknown table `nonexistent_table`."

    async def test_quality_check_output_complex_query_with_joins(self):
        """Test quality check success with complex query including joins."""
        mixin = self._node

        complex_output = SQLSchemaGeneratorOutput(
            query=AssistantHogQLQuery(
                query="SELECT e.event, p.id FROM events e LEFT JOIN persons p ON e.person_id = p.id LIMIT 10"
            ),
            name="",
            description="",
        )

        # Should not raise any exception for valid complex SQL
        await mixin._quality_check_output(complex_output)
