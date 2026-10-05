from parameterized import parameterized

from products.ai_observability.backend.providers.formatters.gemini_formatter import convert_anthropic_messages_to_gemini


class TestConvertAnthropicMessagesToGemini:
    @parameterized.expand(
        [
            ("dict_input", {"location": "Paris"}, {"location": "Paris"}),
            ("json_string_input", '{"location": "Paris"}', {"location": "Paris"}),
            ("unparseable_string_input", "not json", {}),
        ]
    )
    def test_tool_use_becomes_function_call(self, _name, input_value, expected_args):
        contents = convert_anthropic_messages_to_gemini(
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
        assert content.parts[0].text == "Checking the weather."
        function_call = content.parts[1].function_call
        assert function_call.id == "call_1"
        assert function_call.name == "get_weather"
        assert function_call.args == expected_args

    @parameterized.expand(
        [
            ("plain_string", "Sunny, 21C", {"result": "Sunny, 21C"}),
            ("json_object_string", '{"temperature": 21}', {"temperature": 21}),
            ("text_block_list", [{"type": "text", "text": "Sunny, 21C"}], {"result": "Sunny, 21C"}),
        ]
    )
    def test_tool_result_becomes_function_response(self, _name, result_content, expected_response):
        contents = convert_anthropic_messages_to_gemini(
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
        function_response = contents[1].parts[0].function_response
        assert function_response.id == "call_1"
        assert function_response.name == "get_weather"
        assert function_response.response == expected_response

    def test_errored_tool_result_becomes_error_response(self):
        contents = convert_anthropic_messages_to_gemini(
            [
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "boom", "is_error": True}],
                }
            ]
        )

        assert contents[0].parts[0].function_response.response == {"error": "boom"}

    def test_tool_result_without_matching_tool_use_falls_back_to_call_id(self):
        contents = convert_anthropic_messages_to_gemini(
            [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_9", "content": "ok"}]}]
        )

        assert contents[0].parts[0].function_response.name == "call_9"
