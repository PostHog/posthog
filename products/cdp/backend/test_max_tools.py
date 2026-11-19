import json

import pytest
from unittest import mock

from langchain_core.messages import AIMessage
from parameterized import parameterized

from posthog.dataclasses import frozen

from products.cdp.backend.max_tools import CreateHogFunctionInputsTool, CreateHogTransformationFunctionTool

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException

SLACK_INPUTS_SCHEMA = [
    {"key": "slack_workspace", "type": "integration", "label": "Slack workspace", "secret": False},
    {"key": "blocks", "type": "json", "label": "Blocks", "secret": False},
    {"key": "channel_name", "type": "string", "label": "Channel name", "secret": False},
    {"key": "footer", "type": "string", "label": "Footer", "secret": False, "required": False},
    {"key": "title", "type": "string", "label": "Title", "secret": False, "required": True},
    {"key": "signing_secret", "type": "string", "label": "Signing secret", "secret": True},
]

SLACK_BLOCKS = [{"type": "section", "text": {"type": "plain_text", "text": "Old text"}}]
NEW_SLACK_BLOCKS = [{"type": "section", "text": {"type": "plain_text", "text": "New text"}}]


@frozen
class InputsToolRun:
    prompt: str
    content: str
    artifact: object


def _run_inputs_tool(context: dict, model_output: str) -> InputsToolRun:
    config = {"configurable": {"contextual_tools": {"create_hog_function_inputs": context}}}
    tool = CreateHogFunctionInputsTool(team=mock.MagicMock(), user=mock.MagicMock(), config=config)
    model = mock.MagicMock()
    model.invoke.return_value = AIMessage(content=model_output)
    with mock.patch.object(CreateHogFunctionInputsTool, "_model", new_callable=mock.PropertyMock, return_value=model):
        content, artifact = tool._run_impl(instructions="Change the Slack message text to New text")
    prompt = "\n".join(str(message.content) for message in model.invoke.call_args.args[0])
    return InputsToolRun(prompt=prompt, content=content, artifact=artifact)


class TestCreateHogFunctionInputsTool:
    def test_sends_current_values_without_secrets_and_returns_changed_values(self):
        run = _run_inputs_tool(
            {
                "current_inputs_schema": SLACK_INPUTS_SCHEMA,
                "hog_code": "",
                "current_inputs": {
                    "slack_workspace": {"value": 42},
                    "blocks": {"value": SLACK_BLOCKS},
                    "signing_secret": {"value": "schema-secret-value"},
                    "api_token": {"value": "entry-secret-value", "secret": True},
                },
            },
            "<inputs_schema>"
            + json.dumps(SLACK_INPUTS_SCHEMA)
            + "</inputs_schema><input_values>"
            + json.dumps(
                {
                    "blocks": NEW_SLACK_BLOCKS,
                    "signing_secret": "model-secret-value",
                    "slack_workspace": 7,
                    "channel_name": ["not", "a", "string"],
                    "footer": None,
                    "title": None,
                    "not_in_schema": "dropped",
                }
            )
            + "</input_values>",
        )

        assert "Old text" in run.prompt
        assert "schema-secret-value" not in run.prompt
        assert "entry-secret-value" not in run.prompt
        assert run.artifact == {
            "inputs_schema": SLACK_INPUTS_SCHEMA,
            "inputs": {"blocks": NEW_SLACK_BLOCKS, "footer": None},
        }

    def test_returns_schema_list_when_editor_sends_no_input_values(self):
        run = _run_inputs_tool(
            {"current_inputs_schema": SLACK_INPUTS_SCHEMA, "hog_code": ""},
            "<inputs_schema>"
            + json.dumps(SLACK_INPUTS_SCHEMA)
            + "</inputs_schema><input_values>"
            + json.dumps({"blocks": NEW_SLACK_BLOCKS})
            + "</input_values>",
        )

        assert run.artifact == SLACK_INPUTS_SCHEMA
        assert "New text" not in run.content

    def test_drops_values_for_inputs_the_current_schema_locks(self):
        retyped_schema = [
            {**schema, "type": "string", "secret": False}
            if schema["key"] in ("slack_workspace", "signing_secret")
            else schema
            for schema in SLACK_INPUTS_SCHEMA
        ]

        run = _run_inputs_tool(
            {"current_inputs_schema": SLACK_INPUTS_SCHEMA, "hog_code": "", "current_inputs": {}},
            "<inputs_schema>"
            + json.dumps(retyped_schema)
            + "</inputs_schema><input_values>"
            + json.dumps({"slack_workspace": "C123", "signing_secret": "model-secret-value"})
            + "</input_values>",
        )

        assert run.artifact == {"inputs_schema": retyped_schema, "inputs": {}}


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
            (
                "assign_to_global",
                "event := {'name': 'renamed'}\nreturn event",
                'Variable "event" not declared in this scope. Can not assign to globals.',
            ),
            (
                "hyphenated_property",
                "let x := event.some-prop",
                "Use bracket notation: event['some-prop']",
            ),
        ]
    )
    def test_parse_output_includes_specific_parse_error(self, _name, hog_code, expected_fragment):
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        with pytest.raises(PydanticOutputParserException) as exc_info:
            tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert expected_fragment in str(exc_info.value)

    def test_parse_output_valid_code(self):
        hog_code = "let x := 1\nreturn event"
        tool = CreateHogTransformationFunctionTool.__new__(CreateHogTransformationFunctionTool)
        result = tool._parse_output(f"<hog_code>{hog_code}</hog_code>")
        assert result.hog_code == hog_code
