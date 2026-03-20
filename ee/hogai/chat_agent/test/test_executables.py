import unittest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from ee.hogai.utils.bedrock import ANTHROPIC_TO_BEDROCK_MODEL_MAP, to_bedrock_model_id


class TestBedrockModelMapping(unittest.TestCase):
    @parameterized.expand(
        [
            ("claude-sonnet-4-6", "us.anthropic.claude-sonnet-4-6"),
            ("claude-sonnet-4-5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
            ("claude-opus-4-5-20251101", "us.anthropic.claude-opus-4-5-20251101-v1:0"),
            ("claude-opus-4-6", "us.anthropic.claude-opus-4-6"),
            ("claude-haiku-4-5", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        ]
    )
    def test_model_mapping(self, anthropic_model, expected_bedrock_model):
        self.assertEqual(to_bedrock_model_id(anthropic_model), expected_bedrock_model)

    def test_unknown_model_raises(self):
        with self.assertRaises(ValueError):
            to_bedrock_model_id("unknown-model")

    def test_all_agent_models_have_mapping(self):
        agent_models = ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5"]
        for model in agent_models:
            self.assertIn(model, ANTHROPIC_TO_BEDROCK_MODEL_MAP)


class TestChatAgentGatewayRouting(BaseTest):
    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_bedrock_feature_flag",
        return_value=True,
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    def test_get_model_routes_to_llm_gateway_when_feature_flag_enabled(self, mock_model_init, _mock_flag):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        with patch("ee.hogai.core.agent_modes.executables.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_URL = "http://gateway:3308"
            mock_settings.LLM_GATEWAY_API_KEY = "test-key"

            executable = ChatAgentExecutable(
                team=self.team,
                user=self.user,
                toolkit_manager_class=None,
                prompt_builder_class=None,
                node_path=(),
            )

            state = AssistantState(messages=[])
            executable._get_model(state, [])

            call_kwargs = mock_model_init.call_args.kwargs
            self.assertEqual(call_kwargs["anthropic_api_url"], "http://gateway:3308/posthog-ai/bedrock")
            self.assertEqual(call_kwargs["anthropic_api_key"], "test-key")
            self.assertEqual(call_kwargs["model"], "us.anthropic.claude-sonnet-4-6")

    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_bedrock_feature_flag",
        return_value=False,
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    def test_get_model_does_not_route_when_feature_flag_disabled(self, mock_model_init, _mock_flag):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        executable = ChatAgentExecutable(
            team=self.team,
            user=self.user,
            toolkit_manager_class=None,
            prompt_builder_class=None,
            node_path=(),
        )

        state = AssistantState(messages=[])
        executable._get_model(state, [])

        call_kwargs = mock_model_init.call_args.kwargs
        self.assertNotIn("anthropic_api_url", call_kwargs)
        self.assertNotIn("anthropic_api_key", call_kwargs)
        self.assertEqual(call_kwargs["model"], "claude-sonnet-4-6")

    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_bedrock_feature_flag",
        return_value=True,
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    def test_get_model_falls_back_when_gateway_not_configured(self, mock_model_init, _mock_flag):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        with patch("ee.hogai.core.agent_modes.executables.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_URL = ""
            mock_settings.LLM_GATEWAY_API_KEY = ""

            executable = ChatAgentExecutable(
                team=self.team,
                user=self.user,
                toolkit_manager_class=None,
                prompt_builder_class=None,
                node_path=(),
            )

            state = AssistantState(messages=[])
            executable._get_model(state, [])

            call_kwargs = mock_model_init.call_args.kwargs
            self.assertNotIn("anthropic_api_url", call_kwargs)
            self.assertNotIn("anthropic_api_key", call_kwargs)
            # Model name is still converted to Bedrock format even when gateway isn't configured
            self.assertEqual(call_kwargs["model"], "us.anthropic.claude-sonnet-4-6")
