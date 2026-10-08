from products.ai_observability.backend.providers.formatters.openai_formatter import convert_to_openai_messages


class TestConvertToOpenAIMessages:
    def test_tool_use_and_tool_result_round_trip(self):
        result = convert_to_openai_messages(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Checking the weather."},
                        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"location": "Paris"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "Sunny, 21C"}],
                },
            ]
        )

        assert result == [
            {
                "role": "assistant",
                "content": "Checking the weather.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"location": "Paris"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Sunny, 21C"},
        ]
