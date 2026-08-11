import pytest

from parameterized import parameterized

from products.cdp.backend.max_tools import CreateHogTransformationFunctionTool, validate_hog_function_filters

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException


class TestParseOutput:
    @parameterized.expand(
        [
            (
                "slice_syntax",
                "let x := content[1:2000]",
                "The Hog code failed to compile",
            ),
            (
                "double_ampersand",
                "if (a && b) { print(a) }",
                "unexpected character '&' (U+0026)",
            ),
        ]
    )
    def test_parse_output_includes_specific_parse_error(self, _name, hog_code, expected_fragment):
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert expected_fragment in str(exc_info.value)

    def test_parse_output_generic_error_for_non_syntax_issues(self):
        # Code that parses but fails at the HyphenatedPropertyDetector stage
        hog_code = "let x := event.some-prop"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert "The Hog code failed to compile" in str(exc_info.value)
        # Should NOT contain a specific parse error since it's not a syntax error
        assert "no viable alternative" not in str(exc_info.value)

    def test_parse_output_valid_code(self):
        hog_code = "let x := 1\nreturn event"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        result = tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert result.hog_code == hog_code


class TestValidateHogFunctionFilters:
    def test_accepts_well_formed_filters(self):
        filters = {
            "events": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "name": "$pageview",
                    "order": 0,
                    "properties": [{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}],
                }
            ],
            "properties": [{"key": "email", "value": ["a@example.com"], "operator": "exact", "type": "person"}],
        }
        validate_hog_function_filters(filters)

    @parameterized.expand(
        [
            ("unknown_property_type", {"properties": [{"key": "email", "value": "x", "type": "bogus"}]}),
            ("property_missing_type", {"properties": [{"key": "email", "value": "x"}]}),
            ("nested_property_unknown_type", {"events": [{"id": "$pageview", "properties": [{"type": "bogus"}]}]}),
            ("property_not_an_object", {"properties": ["not-a-filter"]}),
            ("events_not_a_list", {"events": {"id": "$pageview"}}),
            ("filters_not_an_object", ["not", "a", "dict"]),
        ]
    )
    def test_rejects_malformed_filters(self, _name, filters):
        with pytest.raises(PydanticOutputParserException):
            validate_hog_function_filters(filters)
