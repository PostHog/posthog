from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized


class TestChatAgentWebSearchToolInclusion(BaseTest):
    @parameterized.expand(
        [
            ("control", True),
            ("gateway-anthropic", True),
            ("gateway-bedrock", False),
        ]
    )
    @patch("ee.hogai.core.agent_modes.toolkit.AgentToolkitManager.get_tools", new_callable=AsyncMock)
    async def test_web_search_included_based_on_variant(self, variant, should_include, mock_get_tools):
        from ee.hogai.chat_agent.toolkit import ChatAgentToolkitManager
        from ee.hogai.utils.types.base import AssistantState

        mock_get_tools.return_value = []

        with (
            patch("ee.hogai.chat_agent.toolkit.get_llm_gateway_variant", return_value=variant),
            patch("ee.hogai.chat_agent.toolkit.settings") as mock_settings,
            patch("ee.hogai.chat_agent.toolkit.has_mcp_servers_feature_flag", return_value=False),
        ):
            mock_settings.LLM_GATEWAY_URL = "http://gateway:3308"
            mock_settings.LLM_GATEWAY_API_KEY = "test-key"

            manager = ChatAgentToolkitManager(team=self.team, user=self.user, context_manager=MagicMock())
            tools = await manager.get_tools(AssistantState(messages=[]), RunnableConfig(configurable={}))

            web_search_tools = [t for t in tools if isinstance(t, dict) and t.get("type") == "web_search_20250305"]

            if should_include:
                self.assertEqual(len(web_search_tools), 1)
            else:
                self.assertEqual(len(web_search_tools), 0)


class TestChatAgentGatewayRouting(BaseTest):
    @parameterized.expand(
        [
            (
                "gateway_bedrock",
                "gateway-bedrock",
                {
                    "X-PostHog-Provider": "bedrock",
                    "X-POSTHOG-FLAG-phai-llm-gateway": "gateway-bedrock",
                },
            ),
            (
                "gateway_anthropic",
                "gateway-anthropic",
                {
                    "X-PostHog-Use-Bedrock-Fallback": "true",
                    "X-POSTHOG-FLAG-phai-llm-gateway": "gateway-anthropic",
                },
            ),
        ]
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch("ee.hogai.core.agent_modes.executables.get_llm_gateway_variant")
    def test_get_model_routes_to_gateway(self, _name, variant, expected_headers, mock_get_variant, mock_model_init):
        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        mock_get_variant.return_value = variant

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
                    self.assertEqual(call_kwargs["default_headers"], expected_headers)
                    self.assertIs(call_kwargs["bypass_proxy"], True)
                    self.assertEqual(call_kwargs["model"], "claude-sonnet-4-6")

    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.get_llm_gateway_variant",
        return_value="control",
    )
    def test_get_model_does_not_route_when_control_variant(self, _mock_variant, mock_model_init):
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

    @parameterized.expand(
        [
            ("default", None, None, "product_analytics", None),
            ("error_tracking", "error_tracking", None, "error_tracking", None),
            ("plan_mode_over_sql", "sql", "plan", "sql", "plan"),
            ("plan_mode_default", "plan", None, "sql", None),
        ]
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.get_llm_gateway_variant",
        return_value="control",
    )
    def test_get_model_tags_generation_with_agent_mode(
        self,
        _name,
        agent_mode,
        supermode,
        expected_agent_mode,
        expected_supermode,
        _mock_variant,
        mock_model_init,
    ):
        from posthog.schema import AgentMode

        from ee.hogai.chat_agent.executables import ChatAgentExecutable
        from ee.hogai.utils.types.base import AssistantState

        executable = ChatAgentExecutable(
            team=self.team,
            user=self.user,
            toolkit_manager_class=MagicMock(),
            prompt_builder_class=MagicMock(),
            node_path=(),
        )

        state = AssistantState(
            messages=[],
            agent_mode=AgentMode(agent_mode) if agent_mode else None,
            supermode=AgentMode(supermode) if supermode else None,
        )
        executable._get_model(state, [])

        call_kwargs = mock_model_init.call_args.kwargs
        self.assertIn("posthog_properties", call_kwargs)
        self.assertEqual(call_kwargs["posthog_properties"]["agent_mode"], expected_agent_mode)
        self.assertEqual(call_kwargs["posthog_properties"]["supermode"], expected_supermode)

    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    @patch(
        "ee.hogai.core.agent_modes.executables.get_llm_gateway_variant",
        return_value="gateway-bedrock",
    )
    def test_get_model_falls_back_when_gateway_not_configured(self, _mock_variant, mock_model_init):
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
