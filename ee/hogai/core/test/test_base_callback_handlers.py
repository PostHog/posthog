from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

import posthoganalytics
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.hogai.core.runner import SubagentCallbackHandler
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

            assert runner._callback_handlers == []

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

            assert len(runner._callback_handlers) == 1
            assert isinstance(runner._callback_handlers[0], CallbackHandler)

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

        assert len(runner._callback_handlers) == 1
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

        assert len(runner._callback_handlers) == 2
        assert mock_get_client.call_count == 2
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

        assert runner._callback_handlers == []

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

            assert len(runner._callback_handlers) == 1

            call_args = mock_callback_handler_class.call_args
            assert call_args[0][0] == mock_client
            assert call_args[1]["distinct_id"] == self.user.distinct_id
            assert call_args[1]["trace_id"] == trace_id

            properties = call_args[1]["properties"]
            assert properties["conversation_id"] == str(self.conversation.id)
            assert properties["$ai_session_id"] == str(self.conversation.id)
            assert properties["is_first_conversation"]
            assert properties["$session_id"] == session_id

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
        assert config["callbacks"] == runner._callback_handlers
        assert len(config["callbacks"]) == 1

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_subagent_callback_handler_used_when_parent_span_id_provided(
        self, mock_get_client, mock_get_region, mock_is_cloud
    ):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "US"
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        parent_span_id = uuid4()
        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
            parent_span_id=parent_span_id,
        )

        assert len(runner._callback_handlers) == 1
        assert isinstance(runner._callback_handlers[0], SubagentCallbackHandler)
        assert isinstance(runner._callback_handlers[0], SubagentCallbackHandler)
        assert runner._callback_handlers[0]._parent_span_id == parent_span_id

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_regular_callback_handler_used_without_parent_span_id(
        self, mock_get_client, mock_get_region, mock_is_cloud
    ):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "US"
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        runner = ChatAgentRunner(
            team=self.team,
            conversation=self.conversation,
            user=self.user,
        )

        assert len(runner._callback_handlers) == 1
        assert isinstance(runner._callback_handlers[0], CallbackHandler)
        assert not isinstance(runner._callback_handlers[0], SubagentCallbackHandler)


class TestSubagentCallbackHandler(BaseTest):
    def setUp(self):
        super().setUp()
        self.mock_client = Mock()
        self.parent_span_id = uuid4()
        self.handler = SubagentCallbackHandler(
            self.mock_client,
            distinct_id="test-user",
            parent_span_id=self.parent_span_id,
        )

    def test_parent_span_id_stored_as_uuid(self):
        assert self.handler._parent_span_id == self.parent_span_id

    def test_parent_span_id_string_converted_to_uuid(self):
        string_id = str(uuid4())
        handler = SubagentCallbackHandler(
            self.mock_client,
            distinct_id="test-user",
            parent_span_id=string_id,
        )
        from uuid import UUID

        assert isinstance(handler._parent_span_id, UUID)
        assert str(handler._parent_span_id) == string_id

    def test_regular_callback_handler_emits_trace_for_root_chains(self):
        """Verify the baseline: regular CallbackHandler emits $ai_trace for root-level chains."""
        mock_client = Mock()
        regular_handler = CallbackHandler(mock_client, distinct_id="test", trace_id="trace-123")

        run_id = uuid4()
        regular_handler.on_chain_start({"name": "TestChain"}, {"input": "test"}, run_id=run_id, parent_run_id=None)
        regular_handler.on_chain_end({"output": "result"}, run_id=run_id, parent_run_id=None)

        capture_calls = list(mock_client.capture.call_args_list)
        assert len(capture_calls) == 1
        event_name = capture_calls[0][1]["event"]
        assert event_name == "$ai_trace"

    def test_subagent_handler_emits_span_for_root_chains(self):
        """SubagentCallbackHandler emits $ai_span (not $ai_trace) for root-level chains."""
        run_id = uuid4()
        self.handler.on_chain_start({"name": "SubagentChain"}, {"input": "test"}, run_id=run_id, parent_run_id=None)
        self.handler.on_chain_end({"output": "result"}, run_id=run_id, parent_run_id=None)

        capture_calls = list(self.mock_client.capture.call_args_list)
        assert len(capture_calls) == 1

        event_name = capture_calls[0][1]["event"]
        properties = capture_calls[0][1]["properties"]

        assert event_name == "$ai_span"
        assert properties["$ai_parent_id"] == self.parent_span_id

    def test_subagent_handler_nested_chains_have_correct_parents(self):
        """Nested chains in SubagentCallbackHandler maintain correct parent relationships."""
        root_run_id = uuid4()
        child_run_id = uuid4()

        # Simulate nested chain execution
        self.handler.on_chain_start({"name": "RootChain"}, {"input": "test"}, run_id=root_run_id, parent_run_id=None)
        self.handler.on_chain_start(
            {"name": "ChildChain"}, {"input": "test"}, run_id=child_run_id, parent_run_id=root_run_id
        )
        self.handler.on_chain_end({"output": "child_result"}, run_id=child_run_id, parent_run_id=root_run_id)
        self.handler.on_chain_end({"output": "root_result"}, run_id=root_run_id, parent_run_id=None)

        capture_calls = list(self.mock_client.capture.call_args_list)
        assert len(capture_calls) == 2

        # First capture is child chain (ends first) - should be $ai_span
        child_event = capture_calls[0][1]["event"]
        assert child_event == "$ai_span"

        # Second capture is root chain - should be $ai_span with injected parent_span_id
        root_event = capture_calls[1][1]["event"]
        root_props = capture_calls[1][1]["properties"]
        assert root_event == "$ai_span"
        assert root_props["$ai_parent_id"] == self.parent_span_id
