import pytest

from parameterized import parameterized

from products.cdp.backend.max_tools import CreateHogTransformationFunctionTool

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException


class TestParseOutput:
    @parameterized.expand(
        [
            (
                "slice_syntax",
                "let x := content[1:2000]",
                "BytecodeCompiler has no method visit_array_slice",
            ),
            (
                "double_ampersand",
                "if (a && b) { print(a) }",
                "unexpected character '&' (U+0026)",
            ),
            (
                "brace_escape_placeholder",
                'let x := f\'{{"filterGroups":[{"a": {event.b}}]}}\'',
                "Placeholders are not allowed in this context",
            ),
            (
                "assignment_to_global",
                "event := 1",
                'Variable "event" not declared in this scope',
            ),
            (
                "hyphenated_property",
                "let x := event.some-prop",
                "Hyphens are not supported in identifiers",
            ),
        ]
    )
    def test_parse_output_reports_the_compiler_reason(self, _name, hog_code, expected_fragment):
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        message = str(exc_info.value)
        assert "The Hog code failed to compile" in message
        assert expected_fragment in message

    def test_parse_output_valid_code(self):
        hog_code = "let x := 1\nreturn event"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        result = tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert result.hog_code == hog_code
