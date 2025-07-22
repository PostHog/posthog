"""
Test to verify that AI assistant nodes handle user JSON input safely.

This test ensures that when users provide JSON content with curly braces,
the ChatPromptTemplate doesn't interpret them as template variables and
cause KeyError exceptions.
"""

import pytest
from langchain_core.prompts import ChatPromptTemplate


class TestUserJSONSafety:
    """Test that all AI assistant nodes handle user JSON input safely."""

    def test_title_generator_with_user_json(self):
        """Test that TitleGeneratorNode handles JSON input correctly."""
        from ee.hogai.graph.title_generator.prompts import TITLE_GENERATION_PROMPT

        # The problematic user input (JSON with curly braces)
        user_input = """Hi Max,

The query below is currently set up as an SQL insight, but the visualization options for SQL insights are quite limited. Could you help convert this into a Trends Insight instead?

```sql
{
  "kind": "DataVisualizationNode",
  "source": {
    "kind": "HogQLQuery",
    "query": "WITH eligible_users AS (SELECT DISTINCT distinct_id FROM events WHERE event = 'CompleteRegistration' AND timestamp < now() - INTERVAL 7 DAY) SELECT e.event, count(e.uuid) AS event_count FROM events e CROSS JOIN eligible_users eu WHERE e.distinct_id = eu.distinct_id AND e.timestamp >= now() - INTERVAL 30 DAY AND e.timestamp < now() GROUP BY e.event ORDER BY event_count DESC"
  },
  "tableSettings": {
    "conditionalFormatting": []
  },
  "chartSettings": {}
}
```"""

        # Test the fixed approach (what's now in the code)
        runnable = ChatPromptTemplate.from_messages([("system", TITLE_GENERATION_PROMPT), ("user", "{user_input}")])

        # This should not raise a KeyError
        result = runnable.format(user_input=user_input)

        # Verify the JSON content is preserved literally
        assert '"kind": "DataVisualizationNode"' in result
        assert '"kind": "HogQLQuery"' in result
        assert user_input in result

    def test_memory_compression_with_json_content(self):
        """Test that MemoryCompressionNode handles JSON in memory content."""
        from ee.hogai.graph.memory.prompts import ONBOARDING_COMPRESSION_PROMPT

        # Simulate memory content that could contain JSON
        memory_content = """Question: What kind of data do you track?
Answer: We track user events like this:
{
  "event": "user_signup",
  "properties": {
    "plan": "free"
  }
}
Additional context: We also store configuration as JSON like {"feature_flags": {"experiment_1": true}}"""

        # Test the fixed approach
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", ONBOARDING_COMPRESSION_PROMPT),
                ("human", "{memory_content}"),
            ]
        )

        # This should not raise a KeyError
        result = prompt.format(memory_content=memory_content)

        # Verify the JSON content is preserved literally
        assert '"event": "user_signup"' in result
        assert '"feature_flags": {"experiment_1": true}' in result
        assert memory_content in result

    def test_broken_patterns_fail_as_expected(self):
        """Test that the original broken patterns would fail."""

        json_content = """{"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery"}}"""

        # This is the pattern that was causing issues (direct embedding)
        try:
            broken_template = ChatPromptTemplate.from_messages(
                [
                    ("system", "Generate a title"),
                    ("user", json_content),  # Direct inclusion
                ]
            )
            broken_template.format()
            # If this doesn't fail, it means LangChain changed behavior
            pytest.fail("Expected KeyError was not raised")

        except Exception as e:
            # Should fail with KeyError mentioning 'kind'
            assert "kind" in str(e) or "missing variables" in str(e)

    def test_complex_nested_json(self):
        """Test with complex nested JSON structures."""

        complex_json = """{
  "level1": {
    "level2": {
      "array": [
        {"item": "value1", "nested": {"deep": "value"}},
        {"item": "value2", "config": {"setting": true}}
      ]
    }
  },
  "variables": {
    "template_var": "should not be interpreted",
    "curly_braces": "everywhere {here} and {there}"
  }
}"""

        # Test safe handling
        template = ChatPromptTemplate.from_messages([("system", "Process this data"), ("user", "{user_data}")])

        result = template.format(user_data=complex_json)

        # Verify all JSON content is preserved
        assert '"level1":' in result
        assert '"template_var": "should not be interpreted"' in result
        assert '"curly_braces": "everywhere {here} and {there}"' in result

    def test_edge_cases(self):
        """Test edge cases with unusual JSON patterns."""

        edge_cases = [
            # Escaped quotes in JSON
            '{"message": "He said \\"Hello\\" to me"}',
            # JSON with newlines
            """{\n  "multiline": "value",\n  "kind": "test"\n}""",
            # Mixed content
            """Here is some text and then JSON: {"kind": "DataVisualizationNode"} and more text.""",
            # Multiple JSON objects
            """{"first": "object"} and {"second": "object", "kind": "test"}""",
        ]

        template = ChatPromptTemplate.from_messages([("system", "Process this"), ("user", "{content}")])

        for test_content in edge_cases:
            # Should not raise KeyError
            result = template.format(content=test_content)
            assert test_content in result


if __name__ == "__main__":
    test_suite = TestUserJSONSafety()

    try:
        test_suite.test_title_generator_with_user_json()
        test_suite.test_memory_compression_with_json_content()
        test_suite.test_broken_patterns_fail_as_expected()
        test_suite.test_complex_nested_json()
        test_suite.test_edge_cases()
    except Exception:
        raise
