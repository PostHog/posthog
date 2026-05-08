"""Tests for message extraction utilities."""

import json

import pytest

from posthog.temporal.llm_analytics.message_utils import extract_text_from_messages, format_tool_definitions


class TestExtractTextFromMessages:
    def test_simple_string(self):
        """Test extraction from simple string"""
        result = extract_text_from_messages("Hello world")
        assert result == "Hello world"

    def test_empty_input(self):
        """Test extraction from empty/None input"""
        assert extract_text_from_messages(None) == ""
        assert extract_text_from_messages("") == ""
        assert extract_text_from_messages([]) == ""

    def test_openai_format(self):
        """Test extraction from OpenAI message format"""
        messages = [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: What is 2+2?\nassistant: 4"

    @pytest.mark.parametrize(
        "label,messages,expected_substring",
        [
            (
                "anthropic_text_blocks",
                [{"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]}],
                "Hi there",
            ),
            (
                "openai_responses_api",
                [{"content": [{"annotations": [], "logprobs": [], "text": "Improving customer experiences."}]}],
                "Improving customer experiences",
            ),
            (
                "unknown_block_shape_fallback",
                [{"content": [{"some_unknown_key": "some_value", "another_key": 42}]}],
                "some_value",
            ),
            (
                "none_text_value",
                [{"content": [{"text": None, "annotations": []}]}],
                "None",
            ),
        ],
    )
    def test_content_block_formats(self, label, messages, expected_substring):
        result = extract_text_from_messages(messages)
        assert expected_substring in result
        assert result != ""

    def test_mixed_content_blocks(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "First part"},
                    {"type": "text", "text": "Second part"},
                ],
            }
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: First part Second part"

    def test_output_choices_format(self):
        messages = [
            {
                "content": "Looks like today weather decided to audition for a soap opera",
                "role": "assistant",
            }
        ]
        result = extract_text_from_messages(messages)
        assert "soap opera" in result
        assert "assistant:" in result

    def test_single_dict_message(self):
        # Single-dict input renders symmetrically with the list path so the
        # role prefix and tool_call_id correlation reach the judge regardless
        # of whether the caller wraps the message in a list.
        message = {"role": "user", "content": "Hello"}
        result = extract_text_from_messages(message)
        assert result == "user: Hello"

    def test_single_dict_tool_result_surfaces_call_id(self):
        message = {"role": "tool", "tool_call_id": "call_42", "content": "done"}
        result = extract_text_from_messages(message)
        assert result == "tool[call_42]: done"

    @pytest.mark.parametrize(
        "messages,expected_substrings",
        [
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "send_email",
                                    "arguments": '{"to": "user@example.com"}',
                                },
                            }
                        ],
                    }
                ],
                ["assistant:", "send_email", "user@example.com"],
                id="openai_tool_call_no_text_content",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": "On it.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "update_status",
                                    "arguments": '{"status": "ok"}',
                                },
                            }
                        ],
                    }
                ],
                ["On it.", "update_status", '{"status": "ok"}'],
                id="openai_tool_call_with_text_content",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "1", "type": "function", "function": {"name": "foo", "arguments": "{}"}},
                            {"id": "2", "type": "function", "function": {"name": "bar", "arguments": "{}"}},
                        ],
                    }
                ],
                ["foo", "bar"],
                id="multiple_tool_calls_in_one_message",
            ),
            pytest.param(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "1",
                                "type": "function",
                                "function": {"name": "foo", "arguments": {"x": 1}},
                            }
                        ],
                    }
                ],
                ["foo", '"x"', "1"],
                id="tool_call_with_dict_arguments",
            ),
        ],
    )
    def test_tool_call_rendering(self, messages, expected_substrings):
        result = extract_text_from_messages(messages)
        for substring in expected_substrings:
            assert substring in result, f"missing {substring!r} in {result!r}"

    def test_full_agentic_conversation_preserves_tool_calls_and_results(self):
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "Update placement status."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "update_placement_status",
                            "arguments": '{"status": "approved"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Status updated."},
            {"role": "assistant", "content": "Done."},
        ]
        result = extract_text_from_messages(messages)
        assert "system: You are an agent." in result
        assert "user: Update placement status." in result
        assert "update_placement_status" in result
        assert '{"status": "approved"}' in result
        # The tool result should be paired back to the call that produced it
        # via tool_call_id, so the judge can correlate multi-step flows.
        assert "tool[call_1]: Status updated." in result
        assert "tool_call call_1" in result
        assert "assistant: Done." in result

    def test_tool_call_id_correlation_across_parallel_calls(self):
        # When the model issues two parallel tool calls, the rendered output
        # should let the judge pair each result back to its originating call.
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_a", "type": "function", "function": {"name": "lookup_user", "arguments": "{}"}},
                    {"id": "call_b", "type": "function", "function": {"name": "lookup_org", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_b", "content": "org found"},
            {"role": "tool", "tool_call_id": "call_a", "content": "user found"},
        ]
        result = extract_text_from_messages(messages)
        assert "tool_call call_a: lookup_user" in result
        assert "tool_call call_b: lookup_org" in result
        assert "tool[call_a]: user found" in result
        assert "tool[call_b]: org found" in result

    def test_tool_result_without_id_falls_back_to_role_only(self):
        messages = [{"role": "tool", "content": "raw output"}]
        result = extract_text_from_messages(messages)
        assert result == "tool: raw output"

    @pytest.mark.parametrize(
        "tool_calls",
        [
            pytest.param("not-a-list", id="not_a_list"),
            pytest.param([{"id": "1"}], id="missing_function"),
            pytest.param([{"function": {"name": ""}}], id="empty_name"),
            pytest.param([{"function": "broken"}], id="function_not_dict"),
            pytest.param(["broken"], id="tool_call_not_dict"),
        ],
    )
    def test_malformed_tool_calls_do_not_crash(self, tool_calls):
        messages = [{"role": "assistant", "content": "Hello", "tool_calls": tool_calls}]
        result = extract_text_from_messages(messages)
        assert "Hello" in result

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("", id="empty_string"),
            pytest.param(None, id="null"),
            pytest.param([], id="empty_list"),
        ],
    )
    def test_empty_content_with_role_preserves_slot(self, content):
        messages = [
            {"role": "user", "content": "did anything happen?"},
            {"role": "tool", "tool_call_id": "1", "content": content},
            {"role": "assistant", "content": "yes"},
        ]
        result = extract_text_from_messages(messages)
        assert "user: did anything happen?" in result
        assert "tool[1]:" in result
        assert "assistant: yes" in result

    def test_completely_empty_message_is_skipped(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {},
            {"role": "assistant", "content": "Hello"},
        ]
        result = extract_text_from_messages(messages)
        assert result == "user: Hi\nassistant: Hello"

    def test_single_dict_renders_tool_calls(self):
        message = {
            "role": "assistant",
            "content": "Calling the tool now.",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "foo", "arguments": '{"x": 1}'}}],
        }
        result = extract_text_from_messages(message)
        assert "Calling the tool now." in result
        assert "foo" in result
        assert '{"x": 1}' in result

    def test_single_dict_with_only_tool_calls(self):
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "send_email", "arguments": "{}"}}],
        }
        result = extract_text_from_messages(message)
        assert "send_email" in result


class TestFormatToolDefinitions:
    @pytest.mark.parametrize(
        "tools",
        [
            pytest.param(None, id="none"),
            pytest.param("", id="empty_string"),
            pytest.param([], id="empty_list"),
        ],
    )
    def test_empty_inputs_render_as_empty(self, tools):
        assert format_tool_definitions(tools) == ""

    def test_string_passthrough(self):
        assert format_tool_definitions("custom-stringified-tools") == "custom-stringified-tools"

    def test_openai_function_shape(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "send_email",
                    "description": "Send an email to a recipient.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to": {"type": "string"},
                            "body": {"type": "string"},
                            "subject": {"type": "string"},
                        },
                        "required": ["to", "body"],
                    },
                },
            }
        ]
        result = format_tool_definitions(tools)
        assert "- send_email" in result
        assert "Send an email to a recipient." in result
        # Parameter names are surfaced compactly with `?` for optional ones,
        # rather than dumping the full JSON schema. Specifically, the per-property
        # type info should not leak into the prompt.
        assert "(to, body, subject?)" in result
        assert '"type": "string"' not in result
        assert '"required"' not in result

    def test_anthropic_input_schema_shape(self):
        tools = [
            {
                "name": "lookup_user",
                "description": "Look up a user by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            }
        ]
        result = format_tool_definitions(tools)
        assert "- lookup_user" in result
        assert "Look up a user by id." in result
        assert "(id)" in result

    def test_multiple_tools_each_on_own_line(self):
        tools = [
            {"type": "function", "function": {"name": "tool_a", "description": "A"}},
            {"type": "function", "function": {"name": "tool_b", "description": "B"}},
        ]
        result = format_tool_definitions(tools)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("- tool_a")
        assert lines[1].startswith("- tool_b")

    def test_single_dict_is_treated_as_one_tool(self):
        tools = {"type": "function", "function": {"name": "solo", "description": "Only one"}}
        result = format_tool_definitions(tools)
        assert result.startswith("- solo")
        assert "Only one" in result

    def test_unrecognized_shape_is_stringified_not_dropped(self):
        tools = [{"weird_key": "weird_value"}]
        result = format_tool_definitions(tools)
        assert "weird_key" in result
        assert "weird_value" in result

    def test_name_only_renders_without_description_or_params(self):
        tools = [{"type": "function", "function": {"name": "noop"}}]
        assert format_tool_definitions(tools) == "- noop"

    def test_dict_of_tools_is_flattened(self):
        # A `{tool_name: tool_spec}` mapping should render each value as its
        # own tool rather than being treated as a single nameless tool.
        tools = {
            "lov-view": {"name": "lov-view", "description": "View something"},
            "supabase-migration": {"name": "supabase-migration", "description": "Run a migration"},
        }
        result = format_tool_definitions(tools)
        lines = result.split("\n")
        assert len(lines) == 2
        assert any(line.startswith("- lov-view") for line in lines)
        assert any(line.startswith("- supabase-migration") for line in lines)

    def test_gemini_function_declarations_shape(self):
        tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "send_email",
                        "description": "Send an email.",
                        "parameters": {"type": "object", "properties": {"to": {"type": "string"}}},
                    },
                    {
                        "name": "lookup_user",
                        "description": "Look up a user.",
                        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                    },
                ]
            }
        ]
        result = format_tool_definitions(tools)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("- send_email")
        assert lines[1].startswith("- lookup_user")
        assert "(to?)" in result
        assert "(id?)" in result

    def test_gemini_function_declarations_at_top_level(self):
        # Some captures send Gemini's tool catalog as a bare dict rather than
        # a list-wrapped one — `functionDeclarations` should be recognized as
        # a tool spec carrier in either shape.
        tools = {
            "functionDeclarations": [
                {"name": "send_email", "description": "Send an email."},
                {"name": "lookup_user", "description": "Look up a user."},
            ]
        }
        result = format_tool_definitions(tools)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("- send_email")
        assert lines[1].startswith("- lookup_user")

    def test_openai_camel_case_input_schema_shape(self):
        tools = [
            {
                "name": "lookup_user",
                "description": "Look up a user by id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            }
        ]
        result = format_tool_definitions(tools)
        assert "- lookup_user" in result
        assert "Look up a user by id." in result
        assert "(id)" in result

    def test_dict_of_tools_with_name_in_key_only(self):
        # When tools come as `{tool_name: {description, inputSchema}}` with no
        # explicit `name` key on the value, fall back to using the mapping key.
        tools = {
            "search_docs": {
                "description": "Search docs",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        }
        result = format_tool_definitions(tools)
        assert result.startswith("- search_docs: Search docs")
        assert "(query)" in result

    def test_compact_params_omits_full_schema_payload(self):
        # The full JSON schema (types, descriptions per property, etc.) must
        # not leak into the prompt — we only want parameter names, since
        # dumping a full schema for every tool can blow past the judge's context.
        # Assert against JSON delimiters that can only come from a schema dump
        # (rather than free-form words that could legitimately appear in a
        # tool's name or description).
        tools = [
            {
                "name": "do_thing",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "string", "description": "A long description that should not appear"},
                        "b": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "required": ["a"],
                },
            }
        ]
        result = format_tool_definitions(tools)
        assert "(a, b?)" in result
        assert '"type"' not in result
        assert '"minimum"' not in result
        assert '"description"' not in result

    def test_empty_parameters_dict_is_skipped(self):
        # An explicitly-empty schema (`{}`) is treated as "no params" and
        # the `(...)` parameter suffix is omitted entirely.
        tools = [{"type": "function", "function": {"name": "noop", "description": "Does nothing", "parameters": {}}}]
        assert format_tool_definitions(tools) == "- noop: Does nothing"

    @pytest.mark.parametrize(
        "tools",
        [
            pytest.param(42, id="int"),
            pytest.param(3.14, id="float"),
            pytest.param(True, id="bool"),
        ],
    )
    def test_non_list_non_dict_falls_through_to_json(self, tools):
        # Anything we can't iterate as a list of tool specs gets stringified
        # rather than silently dropped — the judge can still see something.
        result = format_tool_definitions(tools)
        assert result == json.dumps(tools, default=str)
