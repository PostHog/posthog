from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

import posthoganalytics
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.models import Conversation


class TestBaseAgentRunnerCallbackHandlers(BaseTest):
    def setUp(self):
        super().setUp()
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    def test_callback_handler_local_deployment_no_client(self, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = False
        mock_get_region.return_value = None

        with patch.object(posthoganalytics, "default_client", None):
            runner = ChatAgentRunner(
                team=self.team,
                conversation=self.conversation,
                user=self.user,
            )

            self.assertEqual(runner._callback_handlers, [])

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    def test_callback_handler_local_deployment_with_client(self, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = False
        mock_get_region.return_value = None

        mock_client = Mock()
        with patch.object(posthoganalytics, "default_client", mock_client):
            runner = ChatAgentRunner(
                team=self.team,
                conversation=self.conversation,
                user=self.user,
            )

            self.assertEqual(len(runner._callback_handlers), 1)
            self.assertIsInstance(runner._callback_handlers[0], CallbackHandler)

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_callback_handler_cloud_us_region(self, mock_get_client, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "US"

        mock_us_client = Mock()
        mock_get_client.return_value = mock_us_client

        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
        )

        self.assertEqual(len(runner._callback_handlers), 1)
        mock_get_client.assert_called_once_with("US")

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_callback_handler_cloud_eu_region(self, mock_get_client, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "EU"

        mock_eu_client = Mock()
        mock_us_client = Mock()

        def get_client_side_effect(region):
            if region == "EU":
                return mock_eu_client
            elif region == "US":
                return mock_us_client
            return None

        mock_get_client.side_effect = get_client_side_effect

        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
        )

        self.assertEqual(len(runner._callback_handlers), 2)
        self.assertEqual(mock_get_client.call_count, 2)
        mock_get_client.assert_any_call("EU")
        mock_get_client.assert_any_call("US")

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    def test_callback_handler_cloud_no_region(self, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = None

        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
        )

        self.assertEqual(runner._callback_handlers, [])

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_callback_handler_properties(self, mock_get_client, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "US"

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        trace_id = uuid4()
        session_id = "test-session"

        with patch("ee.hogai.core.runner.CallbackHandler") as mock_callback_handler_class:
            mock_handler_instance = Mock()
            mock_callback_handler_class.return_value = mock_handler_instance

            runner = ChatAgentRunner(
                team=self.team,
                conversation=self.conversation,
                user=self.user,
                session_id=session_id,
                trace_id=trace_id,
                is_new_conversation=True,
            )

            self.assertEqual(len(runner._callback_handlers), 1)

            call_args = mock_callback_handler_class.call_args
            self.assertEqual(call_args[0][0], mock_client)
            self.assertEqual(call_args[1]["distinct_id"], self.user.distinct_id)
            self.assertEqual(call_args[1]["trace_id"], trace_id)

            properties = call_args[1]["properties"]
            self.assertEqual(properties["conversation_id"], str(self.conversation.id))
            self.assertEqual(properties["$ai_session_id"], str(self.conversation.id))
            self.assertEqual(properties["is_first_conversation"], True)
            self.assertEqual(properties["$session_id"], session_id)

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_get_config_uses_callback_handlers(self, mock_get_client, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "US"

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
        )

        config = runner._get_config()
        assert isinstance(config["callbacks"], list)
        self.assertEqual(config["callbacks"], runner._callback_handlers)
        self.assertEqual(len(config["callbacks"]), 1)
