from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import httpx
import openai
from langchain_core.runnables import RunnableLambda
from langgraph.types import Send
from parameterized import parameterized

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.chat_agent.scope_gate.nodes import SCOPE_GATE_MESSAGE_SOURCE, ScopeClassification, ScopeGateNode
from ee.hogai.chat_agent.scope_gate.prompts import OUT_OF_SCOPE_REPLY
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import AssistantNodeName

NODES_MODULE = "ee.hogai.chat_agent.scope_gate.nodes"


def _fake_model(structured_output: RunnableLambda) -> MagicMock:
    model = MagicMock()
    model.with_structured_output.return_value = structured_output
    return model


def _verdict_model(verdict: str) -> MagicMock:
    return _fake_model(RunnableLambda(lambda _: ScopeClassification(verdict=verdict)))


def _raising_model(error: Exception) -> MagicMock:
    def raise_error(_):
        raise error

    return _fake_model(RunnableLambda(raise_error))


class TestScopeGateNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.node = ScopeGateNode(self.team, self.user)
        flag_patch = patch(f"{NODES_MODULE}.has_scope_gate_feature_flag", return_value=True)
        capture_patch = patch(f"{NODES_MODULE}.posthoganalytics.capture")
        self.flag = flag_patch.start()
        self.capture = capture_patch.start()
        self.addCleanup(flag_patch.stop)
        self.addCleanup(capture_patch.stop)

    @parameterized.expand(
        [
            ("out_of_scope", _verdict_model("out_of_scope"), True, "out_of_scope"),
            ("in_scope", _verdict_model("in_scope"), False, "in_scope"),
            ("unsure", _verdict_model("unsure"), False, "unsure"),
            ("classifier_error", _raising_model(RuntimeError("provider unavailable")), False, "error"),
            (
                "classifier_timeout",
                _raising_model(openai.APITimeoutError(request=httpx.Request("POST", "https://example.com"))),
                False,
                "timeout",
            ),
        ]
    )
    async def test_only_an_out_of_scope_verdict_blocks(self, _name, model, expect_blocked, expect_verdict):
        state = AssistantState(messages=[HumanMessage(content="Who is Darth Vader?")])
        with patch.object(ScopeGateNode, "_build_model", return_value=model):
            result = await self.node.arun(state, {})

        if expect_blocked:
            assert result is not None
            reply = cast(AssistantMessage, result.messages[0])
            self.assertEqual(reply.content, OUT_OF_SCOPE_REPLY)
            self.assertEqual(reply.meta.source if reply.meta else None, SCOPE_GATE_MESSAGE_SOURCE)
        else:
            self.assertIsNone(result)
        event = self.capture.call_args.kwargs
        self.assertEqual(event["event"], "max_scope_gate_verdict")
        self.assertEqual(event["properties"]["verdict"], expect_verdict)
        self.assertEqual(event["properties"]["blocked"], expect_blocked)

    async def test_classifier_is_skipped_when_flag_is_off(self):
        self.flag.return_value = False
        state = AssistantState(messages=[HumanMessage(content="Who is Darth Vader?")])
        with patch.object(ScopeGateNode, "_build_model") as build_model:
            result = await self.node.arun(state, {})

        self.assertIsNone(result)
        build_model.assert_not_called()
        self.capture.assert_not_called()

    async def test_blocked_reply_ends_the_turn(self):
        state = AssistantState(messages=[HumanMessage(content="Who is Darth Vader?")])
        with patch.object(ScopeGateNode, "_build_model", return_value=_verdict_model("out_of_scope")):
            result = await self.node.arun(state, {})
        assert result is not None

        routed = await self.node.arouter(AssistantState(messages=[*state.messages, *result.messages]))
        self.assertEqual(routed, AssistantNodeName.END)

    async def test_passed_message_continues_to_root(self):
        state = AssistantState(messages=[HumanMessage(content="Why did signups drop?")])
        routed = await self.node.arouter(state)

        send_list = cast(list[Send], routed)
        self.assertEqual(
            [send.node for send in send_list], [AssistantNodeName.ROOT, AssistantNodeName.MEMORY_COLLECTOR]
        )
