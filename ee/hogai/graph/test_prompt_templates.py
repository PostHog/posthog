"""
Tests to verify that prompt templates are properly escaped for mustache format.

This test ensures that JSON examples in AI assistant prompts don't cause
KeyError exceptions due to unescaped curly braces being interpreted as template variables.
"""

from langchain_core.prompts import ChatPromptTemplate


class TestPromptTemplates:
    """Test that all AI assistant prompt templates work correctly with mustache format."""

    def test_trends_prompt_template_mustache_formatting(self):
        """Test that trends prompt template can be formatted without KeyError."""
        from ee.hogai.graph.trends.prompts import TRENDS_SYSTEM_PROMPT

        prompt = ChatPromptTemplate.from_messages([("system", TRENDS_SYSTEM_PROMPT)], template_format="mustache")

        # Should not raise KeyError about missing 'kind' variables
        result = prompt.format(
            project_name="Test Project", project_datetime="2025-07-22 12:00:00", project_timezone="UTC"
        )

        # Verify JSON examples are properly rendered as literals
        assert '"kind":"TrendsQuery"' in result
        assert '"kind":"EventsNode"' in result
        assert "Test Project" in result

    def test_funnel_prompt_template_mustache_formatting(self):
        """Test that funnel prompt template can be formatted without KeyError."""
        from ee.hogai.graph.funnels.prompts import FUNNEL_SYSTEM_PROMPT

        prompt = ChatPromptTemplate.from_messages([("system", FUNNEL_SYSTEM_PROMPT)], template_format="mustache")

        # Should not raise KeyError
        result = prompt.format(
            project_name="Test Project", project_datetime="2025-07-22 12:00:00", project_timezone="UTC"
        )

        assert '"kind":"FunnelsQuery"' in result
        assert '"kind":"EventsNode"' in result
        assert "Test Project" in result

    def test_retention_prompt_template_mustache_formatting(self):
        """Test that retention prompt template can be formatted without KeyError."""
        from ee.hogai.graph.retention.prompts import RETENTION_SYSTEM_PROMPT

        prompt = ChatPromptTemplate.from_messages([("system", RETENTION_SYSTEM_PROMPT)], template_format="mustache")

        # Should not raise KeyError
        result = prompt.format(
            project_name="Test Project", project_datetime="2025-07-22 12:00:00", project_timezone="UTC"
        )

        assert '"kind":"RetentionQuery"' in result
        assert "Test Project" in result

    def test_json_examples_are_literal_not_variables(self):
        """Test that JSON examples in prompts are treated as literal text."""
        # This template simulates the structure of our prompt files
        # In mustache templates, to output literal JSON, we don't wrap it in {{}}
        test_template = """
Example query:
```
{"kind":"TestQuery","param":"{{{variable_name}}}"}
```
"""

        prompt = ChatPromptTemplate.from_messages([("system", test_template)], template_format="mustache")

        result = prompt.format(variable_name="test_value")

        # The JSON structure should be literal, but the variable should be substituted
        assert '"kind":"TestQuery"' in result
        assert '"param":"test_value"' in result
        # Should not contain template syntax
        assert "{{{variable_name}}}" not in result
