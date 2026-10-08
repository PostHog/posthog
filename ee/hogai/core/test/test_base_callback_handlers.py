import asyncio
from functools import partial
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import posthoganalytics
from asgiref.sync import async_to_sync
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from opentelemetry import trace
from parameterized import parameterized
from posthoganalytics.ai.langchain.callbacks import CallbackHandler

from posthog.ph_client import get_client

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.chat_agent.runner import ChatAgentRunner
from ee.hogai.core.ai_event_truncation import ai_event_truncator
from ee.hogai.core.runner import MaxCallbackHandler, SubagentCallbackHandler
from ee.hogai.llm import AI_GATEWAY_SERVED_KEY


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

        client = posthoganalytics.Posthog("test-key", send=False)
        self.addCleanup(client.shutdown)
        with patch.object(posthoganalytics, "default_client", client):
            runner = ChatAgentRunner(
                team=self.team,
                conversation=self.conversation,
                user=self.user,
            )

            self.assertEqual(len(runner._callback_handlers), 1)
            self.assertIsInstance(runner._callback_handlers[0], CallbackHandler)
            self.assertFalse(client.capture_trace_context)

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
        mock_get_client.assert_called_once_with(
            "US",
            flush_at=1,
            before_send=ai_event_truncator,
            capture_trace_context=True,
        )

    @patch("ee.hogai.core.runner.is_cloud")
    @patch("ee.hogai.core.runner.get_instance_region")
    @patch("ee.hogai.core.runner.get_client")
    def test_callback_handler_cloud_eu_region(self, mock_get_client, mock_get_region, mock_is_cloud):
        mock_is_cloud.return_value = True
        mock_get_region.return_value = "EU"

        mock_eu_client = Mock()
        mock_us_client = Mock()

        def get_client_side_effect(region, **kwargs):
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
        mock_get_client.assert_any_call(
            "EU",
            flush_at=1,
            before_send=ai_event_truncator,
            capture_trace_context=True,
        )
        mock_get_client.assert_any_call(
            "US",
            flush_at=1,
            before_send=ai_event_truncator,
            capture_trace_context=True,
        )

    @parameterized.expand(
        [
            ("sampled", True, True, False),
            ("subagent", True, True, True),
            ("unsampled", True, False, False),
            ("missing_context", False, False, False),
        ]
    )
    def test_callback_events_preserve_run_trace_context(
        self, _name: str, has_context: bool, sampled: bool, is_subagent: bool
    ) -> None:
        parent_span_id = uuid4() if is_subagent else None
        ai_trace_ids = [uuid4(), uuid4()]
        contexts = [
            trace.SpanContext(
                trace_id=index + 1,
                span_id=index + 10,
                is_remote=False,
                trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED if sampled else trace.TraceFlags.DEFAULT),
            )
            for index in range(2)
        ]

        async def synthetic_tool(value: str) -> str:
            return value

        tool = StructuredTool.from_function(
            coroutine=synthetic_tool, name="synthetic_tool", description="Return a synthetic value."
        )

        with (
            patch("ee.hogai.core.runner.is_cloud", return_value=True),
            patch("ee.hogai.core.runner.get_instance_region", return_value="US"),
            patch("ee.hogai.core.runner.get_client", side_effect=partial(get_client, send=False, disabled=False)),
            patch("ee.hogai.core.runner.ai_event_truncator", wraps=ai_event_truncator) as capture,
        ):
            configs: list[RunnableConfig] = []
            for ai_trace_id in ai_trace_ids:
                runner = ChatAgentRunner(
                    team=self.team,
                    conversation=self.conversation,
                    user=self.user,
                    trace_id=ai_trace_id,
                    parent_span_id=parent_span_id,
                )
                configs.append(runner._get_config())
                for handler in runner._callback_handlers:
                    assert isinstance(handler, CallbackHandler)
                    self.addCleanup(handler._ph_client.shutdown)

            async def run_concurrently() -> None:
                barrier = asyncio.Barrier(2)

                async def run(index: int) -> None:
                    span = trace.NonRecordingSpan(contexts[index]) if has_context else trace.INVALID_SPAN
                    with trace.use_span(span):
                        await barrier.wait()
                        model = FakeListChatModel(responses=["synthetic response"])
                        async for _chunk in model.astream("synthetic input", config=configs[index]):
                            pass
                        await tool.ainvoke({"value": "synthetic value"}, config=configs[index])

                await asyncio.gather(run(0), run(1))

            async_to_sync(run_concurrently)()

        for index, ai_trace_id in enumerate(ai_trace_ids):
            events = [
                call.args[0]
                for call in capture.call_args_list
                if str(call.args[0]["properties"].get("$ai_trace_id")) == str(ai_trace_id)
            ]
            self.assertCountEqual(
                [event["event"] for event in events], ["$ai_generation", "$ai_span" if is_subagent else "$ai_trace"]
            )
            for event in events:
                properties = event["properties"]
                self.assertTrue(properties["$ai_span_id"])
                if is_subagent:
                    self.assertEqual(str(properties["$ai_parent_id"]), str(parent_span_id))
                if has_context:
                    self.assertEqual(properties["$trace_id"], f"{contexts[index].trace_id:032x}")
                    self.assertEqual(properties["$span_id"], f"{contexts[index].span_id:016x}")
                    self.assertNotEqual(str(properties["$ai_span_id"]), properties["$span_id"])
                else:
                    self.assertNotIn("$trace_id", properties)
                    self.assertNotIn("$span_id", properties)

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

        with patch("ee.hogai.core.runner.MaxCallbackHandler") as mock_callback_handler_class:
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

        self.assertEqual(len(runner._callback_handlers), 1)
        self.assertIsInstance(runner._callback_handlers[0], SubagentCallbackHandler)
        assert isinstance(runner._callback_handlers[0], SubagentCallbackHandler)
        self.assertEqual(runner._callback_handlers[0]._parent_span_id, parent_span_id)

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

        self.assertEqual(len(runner._callback_handlers), 1)
        self.assertIsInstance(runner._callback_handlers[0], CallbackHandler)
        self.assertNotIsInstance(runner._callback_handlers[0], SubagentCallbackHandler)
        self.assertIsInstance(runner._callback_handlers[0], MaxCallbackHandler)


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
        self.assertEqual(self.handler._parent_span_id, self.parent_span_id)

    def test_parent_span_id_string_converted_to_uuid(self):
        string_id = str(uuid4())
        handler = SubagentCallbackHandler(
            self.mock_client,
            distinct_id="test-user",
            parent_span_id=string_id,
        )
        from uuid import UUID

        self.assertIsInstance(handler._parent_span_id, UUID)
        self.assertEqual(str(handler._parent_span_id), string_id)

    def test_regular_callback_handler_emits_trace_for_root_chains(self):
        """Verify the baseline: regular CallbackHandler emits $ai_trace for root-level chains."""
        mock_client = Mock()
        regular_handler = CallbackHandler(mock_client, distinct_id="test", trace_id="trace-123")

        run_id = uuid4()
        regular_handler.on_chain_start({"name": "TestChain"}, {"input": "test"}, run_id=run_id, parent_run_id=None)
        regular_handler.on_chain_end({"output": "result"}, run_id=run_id, parent_run_id=None)

        capture_calls = list(mock_client.capture.call_args_list)
        self.assertEqual(len(capture_calls), 1)
        event_name = capture_calls[0][1]["event"]
        self.assertEqual(event_name, "$ai_trace")

    def test_subagent_handler_emits_span_for_root_chains(self):
        """SubagentCallbackHandler emits $ai_span (not $ai_trace) for root-level chains."""
        run_id = uuid4()
        self.handler.on_chain_start({"name": "SubagentChain"}, {"input": "test"}, run_id=run_id, parent_run_id=None)
        self.handler.on_chain_end({"output": "result"}, run_id=run_id, parent_run_id=None)

        capture_calls = list(self.mock_client.capture.call_args_list)
        self.assertEqual(len(capture_calls), 1)

        event_name = capture_calls[0][1]["event"]
        properties = capture_calls[0][1]["properties"]

        self.assertEqual(event_name, "$ai_span")
        self.assertEqual(properties["$ai_parent_id"], self.parent_span_id)

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
        self.assertEqual(len(capture_calls), 2)

        # First capture is child chain (ends first) - should be $ai_span
        child_event = capture_calls[0][1]["event"]
        self.assertEqual(child_event, "$ai_span")

        # Second capture is root chain - should be $ai_span with injected parent_span_id
        root_event = capture_calls[1][1]["event"]
        root_props = capture_calls[1][1]["properties"]
        self.assertEqual(root_event, "$ai_span")
        self.assertEqual(root_props["$ai_parent_id"], self.parent_span_id)


class TestMaxCallbackHandler(SimpleTestCase):
    def _captured_events(
        self, client: Mock, handler: MaxCallbackHandler, output: LLMResult | BaseException
    ) -> list[str]:
        root_run_id, llm_run_id = uuid4(), uuid4()
        handler.on_chain_start({"name": "Root"}, {"input": "hello"}, run_id=root_run_id, parent_run_id=None)
        handler.on_chat_model_start(
            {"name": "MaxChatAnthropic"},
            [[HumanMessage(content="hello")]],
            run_id=llm_run_id,
            parent_run_id=root_run_id,
        )
        if isinstance(output, BaseException):
            handler.on_llm_error(output, run_id=llm_run_id, parent_run_id=root_run_id)
        else:
            handler.on_llm_end(output, run_id=llm_run_id, parent_run_id=root_run_id)
        handler.on_chain_end({"output": "done"}, run_id=root_run_id, parent_run_id=None)
        return [call.kwargs["event"] for call in client.capture.call_args_list]

    def _result(self, served: bool) -> LLMResult:
        generation_info = {AI_GATEWAY_SERVED_KEY: True} if served else None
        return LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="hi"), generation_info=generation_info)]]
        )

    def test_skips_generations_the_gateway_served_and_keeps_the_trace(self):
        client = Mock()
        handler = MaxCallbackHandler(client, distinct_id="user", trace_id="trace-1")

        self.assertEqual(self._captured_events(client, handler, self._result(served=True)), ["$ai_trace"])

    def test_captures_generations_served_directly(self):
        client = Mock()
        handler = MaxCallbackHandler(client, distinct_id="user", trace_id="trace-1")

        self.assertEqual(
            self._captured_events(client, handler, self._result(served=False)), ["$ai_generation", "$ai_trace"]
        )

    def test_captures_failed_generations(self):
        client = Mock()
        handler = MaxCallbackHandler(client, distinct_id="user", trace_id="trace-1")

        self.assertIn("$ai_generation", self._captured_events(client, handler, ValueError("failed")))

    def test_subagent_handler_skips_generations_the_gateway_served(self):
        client = Mock()
        handler = SubagentCallbackHandler(client, distinct_id="user", trace_id="trace-1", parent_span_id=uuid4())

        self.assertEqual(self._captured_events(client, handler, self._result(served=True)), ["$ai_span"])


class TestRunnerAIGatewayProduct(BaseTest):
    @patch("ee.hogai.core.runner.is_cloud", return_value=True)
    @patch("ee.hogai.core.runner.get_instance_region", return_value="US")
    @patch("ee.hogai.core.runner.get_client", return_value=Mock())
    def test_config_names_the_product_the_root_model_routes_for(self, _mock_get_client, _mock_region, _mock_is_cloud):
        for conversation_type, expected_product in [
            (Conversation.Type.ASSISTANT, "posthog_ai"),
            (Conversation.Type.TOOL_CALL, "mcp"),
        ]:
            with self.subTest(conversation_type=conversation_type):
                conversation = Conversation.objects.create(team=self.team, user=self.user, type=conversation_type)
                runner = ChatAgentRunner(team=self.team, conversation=conversation, user=self.user)

                self.assertEqual(runner._get_config()["configurable"]["ai_product"], expected_product)
                handler = runner._callback_handlers[0]
                assert isinstance(handler, MaxCallbackHandler)
                self.assertEqual((handler._properties or {}).get("ai_product"), expected_product)

    @patch("ee.hogai.core.runner.is_cloud", return_value=True)
    @patch("ee.hogai.core.runner.get_instance_region", return_value="US")
    @patch("ee.hogai.core.runner.get_client", return_value=Mock())
    def test_config_carries_the_privacy_mode_the_handler_redacts_with(
        self, _mock_get_client, _mock_region, _mock_is_cloud
    ):
        conversation = Conversation.objects.create(team=self.team, user=self.user, type=Conversation.Type.ASSISTANT)
        for enabled in (True, False):
            with (
                self.subTest(privacy_mode=enabled),
                patch("ee.hogai.core.runner.is_privacy_mode_enabled", return_value=enabled),
            ):
                runner = ChatAgentRunner(team=self.team, conversation=conversation, user=self.user)

                self.assertIs(runner._get_config()["configurable"]["privacy_mode"], enabled)
                handler = runner._callback_handlers[0]
                assert isinstance(handler, MaxCallbackHandler)
                self.assertIs(handler._privacy_mode, enabled)

    @patch("ee.hogai.core.runner.is_cloud", return_value=True)
    @patch("ee.hogai.core.runner.get_instance_region", return_value="US")
    @patch("ee.hogai.core.runner.get_client", return_value=Mock())
    def test_config_carries_impersonation_for_gateway_rows(self, _mock_get_client, _mock_region, _mock_is_cloud):
        conversation = Conversation.objects.create(team=self.team, user=self.user, type=Conversation.Type.ASSISTANT)
        for is_impersonated in (True, False):
            with self.subTest(is_impersonated=is_impersonated):
                runner = ChatAgentRunner(
                    team=self.team, conversation=conversation, user=self.user, is_impersonated=is_impersonated
                )

                self.assertIs(runner._get_config()["configurable"]["is_impersonated"], is_impersonated)
