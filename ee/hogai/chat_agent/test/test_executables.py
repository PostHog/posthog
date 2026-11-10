from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized


class TestChatAgentModelTagging(BaseTest):
    @parameterized.expand(
        [
            ("default", None, None, "product_analytics", None),
            ("error_tracking", "error_tracking", None, "error_tracking", None),
            ("plan_mode_over_sql", "sql", "plan", "sql", "plan"),
            ("plan_mode_default", "plan", None, "sql", None),
        ]
    )
    @patch("ee.hogai.llm.MaxChatAnthropic.__init__", return_value=None)
    def test_get_model_tags_generation_with_agent_mode(
        self,
        _name,
        agent_mode,
        supermode,
        expected_agent_mode,
        expected_supermode,
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
