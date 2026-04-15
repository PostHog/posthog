from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch


class TestChatAgentGatewayRouting(BaseTest):
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_feature_flag",
        return_value=True,
    )
    def test_get_model_routes_to_llm_gateway_when_feature_flag_enabled(self, _mock_flag, mock_model_init):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        test_cases = [
            ("http://gateway:3308", "http://gateway:3308/django"),
            ("http://gateway:3308/", "http://gateway:3308/django"),
        ]

        for configured_url, expected_gateway_url in test_cases:
            with self.subTest(configured_url=configured_url):
                with patch("ee.hogai.core.agent_modes.executables.settings") as mock_settings:
                    mock_settings.LLM_GATEWAY_URL = configured_url
                    mock_settings.LLM_GATEWAY_API_KEY = "test-key"

                    executable = ChatAgentExecutable(
                        team=self.team,
                        user=self.user,
                        toolkit_manager_class=MagicMock(),
                        prompt_builder_class=MagicMock(),
                        node_path=(),
                    )

                    state = AssistantState(messages=[])
                    executable._get_model(state, [])

                    call_kwargs = mock_model_init.call_args.kwargs
                    self.assertEqual(call_kwargs["anthropic_api_url"], expected_gateway_url)
                    self.assertEqual(call_kwargs["anthropic_api_key"], "test-key")
                    self.assertEqual(call_kwargs["default_headers"], {"X-PostHog-Provider": "bedrock"})
                    self.assertIs(call_kwargs["bypass_proxy"], True)
                    self.assertEqual(call_kwargs["model"], "claude-sonnet-4-6")

    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_feature_flag",
        return_value=False,
    )
    def test_get_model_does_not_route_when_feature_flag_disabled(self, _mock_flag, mock_model_init):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        executable = ChatAgentExecutable(
            team=self.team,
            user=self.user,
            toolkit_manager_class=MagicMock(),
            prompt_builder_class=MagicMock(),
            node_path=(),
        )

        state = AssistantState(messages=[])
        executable._get_model(state, [])

        call_kwargs = mock_model_init.call_args.kwargs
        self.assertNotIn("anthropic_api_url", call_kwargs)
        self.assertNotIn("anthropic_api_key", call_kwargs)
        self.assertNotIn("default_headers", call_kwargs)
        self.assertIs(call_kwargs["bypass_proxy"], False)
        self.assertEqual(call_kwargs["model"], "claude-sonnet-4-6")

    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.has_llm_gateway_feature_flag",
        return_value=True,
    )
    def test_get_model_falls_back_when_gateway_not_configured(self, _mock_flag, mock_model_init):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        with patch("ee.hogai.core.agent_modes.executables.settings") as mock_settings:
            mock_settings.LLM_GATEWAY_URL = ""
            mock_settings.LLM_GATEWAY_API_KEY = ""

            executable = ChatAgentExecutable(
                team=self.team,
                user=self.user,
                toolkit_manager_class=MagicMock(),
                prompt_builder_class=MagicMock(),
                node_path=(),
            )

            state = AssistantState(messages=[])
            executable._get_model(state, [])

            call_kwargs = mock_model_init.call_args.kwargs
            self.assertNotIn("anthropic_api_url", call_kwargs)
            self.assertNotIn("anthropic_api_key", call_kwargs)
            self.assertNotIn("default_headers", call_kwargs)
            self.assertIs(call_kwargs["bypass_proxy"], False)
            self.assertEqual(call_kwargs["model"], "claude-sonnet-4-6")
