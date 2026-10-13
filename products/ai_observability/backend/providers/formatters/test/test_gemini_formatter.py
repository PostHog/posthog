from typing import Any, cast

import pytest

from google.genai.types import Content, FunctionCall, FunctionResponse, Part
from parameterized import parameterized

from products.ai_observability.backend.providers.formatters.gemini_formatter import (
    MessageConversionError,
    convert_anthropic_messages_to_gemini,
)


def _convert(messages: list[dict[str, Any]]) -> list[Content]:
    return cast(list[Content], convert_anthropic_messages_to_gemini(messages))


def _part(content: Content, index: int) -> Part:
    assert content.parts is not None
    return content.parts[index]


def _function_call(content: Content, index: int) -> FunctionCall:
    function_call = _part(content, index).function_call
    assert function_call is not None
    return function_call


def _function_response(content: Content, index: int) -> FunctionResponse:
    function_response = _part(content, index).function_response
    assert function_response is not None
    return function_response


class TestConvertAnthropicMessagesToGemini:
    @parameterized.expand(
        [
            ("dict_input", {"location": "Paris"}, {"location": "Paris"}),
            ("json_string_input", '{"location": "Paris"}', {"location": "Paris"}),
        ]
    )
    def test_tool_use_becomes_function_call(self, _name, input_value, expected_args):
        contents = _convert(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Checking the weather."},
                        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": input_value},
                    ],
                }
            ]
        )

        content = contents[0]
        assert content.role == "model"
        assert _part(content, 0).text == "Checking the weather."
        function_call = _function_call(content, 1)
        assert function_call.id == "call_1"
        assert function_call.name == "get_weather"
        assert function_call.args == expected_args

    @parameterized.expand(
        [
            ("plain_string", "Sunny, 21C", {"result": "Sunny, 21C"}),
            ("json_object_string", '{"temperature": 21}', {"temperature": 21}),
            ("text_block_list", [{"type": "text", "text": "Sunny, 21C"}], {"result": "Sunny, 21C"}),
            (
                "image_only_block_list",
                [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}}],
                {"result": "[image omitted]"},
            ),
        ]
    )
    def test_tool_result_becomes_function_response(self, _name, result_content, expected_response):
        contents = _convert(
            [
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": result_content}],
                },
            ]
        )

        assert contents[1].role == "user"
        function_response = _function_response(contents[1], 0)
        assert function_response.id == "call_1"
        assert function_response.name == "get_weather"
        assert function_response.response == expected_response

    def test_first_function_call_in_a_turn_gets_the_skip_signature(self):
        contents = _convert(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {}},
                        {"type": "tool_use", "id": "call_2", "name": "get_weather", "input": {}},
                    ],
                }
            ]
        )

        assert _part(contents[0], 0).thought_signature == b"skip_thought_signature_validator"
        assert _part(contents[0], 1).thought_signature is None

    def test_unparseable_tool_call_arguments_are_rejected(self):
        with pytest.raises(MessageConversionError, match="get_weather"):
            convert_anthropic_messages_to_gemini(
                [
                    {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "call_1", "name": "get_weather", "input": "not json"}],
                    }
                ]
            )

    def test_errored_tool_result_becomes_error_response(self):
        contents = _convert(
            [
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "boom", "is_error": True}],
                }
            ]
        )

        assert _function_response(contents[0], 0).response == {"error": "boom"}

    def test_tool_result_without_matching_tool_use_falls_back_to_call_id(self):
        contents = _convert(
            [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_9", "content": "ok"}]}]
        )

        assert _function_response(contents[0], 0).name == "call_9"
