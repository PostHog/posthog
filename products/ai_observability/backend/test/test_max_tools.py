from posthog.test.base import BaseTest
from unittest.mock import patch

from langgraph.errors import GraphInterrupt

from products.ai_observability.backend.max_tools import CONTEXT_PROMPT_TEMPLATE, DSL_REFERENCE, CreateParserRecipeTool

from ee.hogai.tool import ClientToolCallRequest
from ee.hogai.utils.types.base import NodePath

VALID_RECIPE = """
rules:
    - on:
          kind: question
      emit:
          role: user
          content: $.body
""".strip()


class TestCreateParserRecipeTool(BaseTest):
    def _create_tool(self) -> CreateParserRecipeTool:
        return CreateParserRecipeTool(
            team=self.team,
            user=self.user,
            node_path=(NodePath(name="root", tool_call_id="call_1", message_id="msg_1"),),
        )

    async def test_invalid_yaml_returns_error_without_client_round_trip(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            content, artifact = await tool._arun_impl(
                name="My SDK", yaml_source="rules: [unclosed", event_uuid="event-1"
            )

            mock_interrupt.assert_not_called()
            self.assertIn("not valid YAML", content)
            self.assertIsNone(artifact)

    async def test_valid_yaml_interrupts_for_client_validation(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.side_effect = GraphInterrupt()

            with self.assertRaises(GraphInterrupt):
                await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            request = mock_interrupt.call_args.args[0]
            self.assertIsInstance(request, ClientToolCallRequest)
            self.assertEqual(request.tool_name, "create_ai_trace_parser")
            self.assertEqual(request.original_tool_call_id, "call_1")

    async def test_valid_verdict_returns_success_with_artifact(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "client_tool_result",
                "result": {"valid": True, "recipe_id": "r1"},
            }

            content, artifact = await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            self.assertIn("saved", content)
            self.assertEqual(artifact, {"recipe_id": "r1", "name": "My SDK", "source": VALID_RECIPE})

    async def test_invalid_verdict_returns_error_for_iteration(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "client_tool_result",
                "result": {"valid": False, "error": "no rule matched the sample input"},
            }

            content, artifact = await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            self.assertIn("no rule matched the sample input", content)
            self.assertIn("call this tool again", content)
            self.assertIsNone(artifact)

    async def test_save_failure_tells_agent_not_to_rewrite(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "client_tool_result",
                "result": {"valid": True, "saved": False, "error": "500 from API"},
            }

            content, artifact = await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            self.assertIn("Do not rewrite the recipe", content)
            self.assertIn("500 from API", content)
            self.assertEqual(artifact, {"name": "My SDK", "source": VALID_RECIPE})

    async def test_wrong_event_refusal_does_not_ask_for_a_rewrite(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "client_tool_result",
                "result": {"valid": False, "wrong_event": True, "error": "the user is now viewing a different event"},
            }

            content, artifact = await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            self.assertIn("different event", content)
            self.assertNotIn("Adjust the recipe", content)
            self.assertIsNone(artifact)

    async def test_client_execution_error_is_reported_without_retrying(self):
        tool = self._create_tool()

        with patch("ee.hogai.tool.interrupt") as mock_interrupt:
            mock_interrupt.return_value = {
                "action": "client_tool_result",
                "result": {"client_execution_error": "The PostHog view that executes this tool is no longer open."},
            }

            content, artifact = await tool._arun_impl(name="My SDK", yaml_source=VALID_RECIPE, event_uuid="event-1")

            self.assertIn("could not be validated client-side", content)
            self.assertIn("do not rewrite the recipe", content)
            self.assertIsNone(artifact)

    def test_context_prompt_template_survives_placeholder_formatting(self):
        tool = self._create_tool()
        context = {
            "event_uuid": "0196f8a0-aaaa-bbbb-cccc-000000000000",
            "event_type": "span",
            "unrecognized": "input",
            "sample_input": '{"foo": 1}',
            "sample_output": '{"bar": 2}',
            "existing_recipes": "(none)",
        }

        rendered = tool.format_context_prompt_injection(context)

        assert rendered is not None
        # Any `{identifier}` introduced into the reference would be substituted away and break containment
        self.assertIn('{"foo": 1}', rendered)
        self.assertIn("Event type: span", rendered)
        self.assertIn(DSL_REFERENCE.strip(), rendered)
        self.assertNotIn("None", rendered)

    def test_context_prompt_template_embeds_dsl_reference(self):
        self.assertIn("examples:", CONTEXT_PROMPT_TEMPLATE)
        self.assertIn("try_parse_structured_content", CONTEXT_PROMPT_TEMPLATE)
