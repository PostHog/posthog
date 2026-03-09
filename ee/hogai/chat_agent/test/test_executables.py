from unittest import TestCase
from unittest.mock import MagicMock, patch

from posthog.schema import HumanMessage

from ee.hogai.chat_agent.executables import ChatAgentExecutable
from ee.hogai.core.agent_modes import executables as agent_executables
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName, NodePath


class DummyToolkitManager:
    pass


class DummyPromptBuilder:
    pass


class TestChatAgentExecutableGatewayRouting(TestCase):
    def _create_node(self) -> ChatAgentExecutable:
        team = MagicMock()
        team.id = 17
        user = MagicMock()
        return ChatAgentExecutable(
            team=team,
            user=user,
            toolkit_manager_class=DummyToolkitManager,
            prompt_builder_class=DummyPromptBuilder,
            node_path=(NodePath(name=AssistantNodeName.ROOT, message_id="msg", tool_call_id="tc"),),
        )

    def test_get_model_routes_to_llm_gateway_when_feature_flag_enabled(self):
        node = self._create_node()
        state = AssistantState(
            messages=[HumanMessage(content="Use the gateway")],
            root_tool_calls_count=node.MAX_TOOL_CALLS,
        )
        mock_model = MagicMock()

        with (
            patch("ee.hogai.chat_agent.executables.has_llm_gateway_feature_flag", return_value=True),
            patch.object(agent_executables.settings, "LLM_GATEWAY_URL", "http://gateway:3308"),
            patch.object(agent_executables.settings, "LLM_GATEWAY_API_KEY", "phx_test_api_key"),
            patch("ee.hogai.core.agent_modes.executables.MaxChatAnthropic", return_value=mock_model) as mock_anthropic,
        ):
            result_model = node._get_model(state, [])

        self.assertEqual(result_model, mock_model)
        self.assertEqual(mock_anthropic.call_args.kwargs["anthropic_api_url"], "http://gateway:3308/wizard")
        self.assertEqual(mock_anthropic.call_args.kwargs["anthropic_api_key"], "phx_test_api_key")

    def test_get_model_does_not_route_to_llm_gateway_when_feature_flag_disabled(self):
        node = self._create_node()
        state = AssistantState(
            messages=[HumanMessage(content="Do not use gateway")],
            root_tool_calls_count=node.MAX_TOOL_CALLS,
        )
        mock_model = MagicMock()

        with (
            patch("ee.hogai.chat_agent.executables.has_llm_gateway_feature_flag", return_value=False),
            patch.object(agent_executables.settings, "LLM_GATEWAY_URL", "http://gateway:3308"),
            patch.object(agent_executables.settings, "LLM_GATEWAY_API_KEY", "phx_test_api_key"),
            patch("ee.hogai.core.agent_modes.executables.MaxChatAnthropic", return_value=mock_model) as mock_anthropic,
        ):
            result_model = node._get_model(state, [])

        self.assertEqual(result_model, mock_model)
        self.assertNotIn("anthropic_api_url", mock_anthropic.call_args.kwargs)
        self.assertNotIn("anthropic_api_key", mock_anthropic.call_args.kwargs)

    def test_get_model_falls_back_when_llm_gateway_not_configured(self):
        node = self._create_node()
        state = AssistantState(
            messages=[HumanMessage(content="Gateway not configured")],
            root_tool_calls_count=node.MAX_TOOL_CALLS,
        )
        mock_model = MagicMock()

        with (
            patch("ee.hogai.chat_agent.executables.has_llm_gateway_feature_flag", return_value=True),
            patch.object(agent_executables.settings, "LLM_GATEWAY_URL", ""),
            patch.object(agent_executables.settings, "LLM_GATEWAY_API_KEY", ""),
            patch("ee.hogai.core.agent_modes.executables.MaxChatAnthropic", return_value=mock_model) as mock_anthropic,
            patch("ee.hogai.core.agent_modes.executables.logger.warning") as mock_warning,
        ):
            result_model = node._get_model(state, [])

        self.assertEqual(result_model, mock_model)
        self.assertNotIn("anthropic_api_url", mock_anthropic.call_args.kwargs)
        self.assertNotIn("anthropic_api_key", mock_anthropic.call_args.kwargs)
        mock_warning.assert_called_once()
