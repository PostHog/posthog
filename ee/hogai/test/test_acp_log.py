"""Unit tests for the sandboxed eval ACP log parser.

These tests exercise ``parse_log`` alone against synthetic JSONL entries that
mimic the agent-server's session log format. They intentionally live outside
``ee/hogai/eval/`` so they run under the default pytest configuration — no
Temporal worker, no Docker sandbox, no Django live server.
"""

from __future__ import annotations

import json

from posthog.test.base import BaseTest

from ee.hogai.eval.sandboxed.acp_log import parse_log


def _notification(**params) -> dict:
    return {
        "type": "notification",
        "timestamp": params.pop("ts"),
        "notification": {
            "jsonrpc": "2.0",
            "method": params.pop("method", "session/update"),
            "params": params.pop("params", {}),
        },
    }


def _session_update(ts: str, update: dict) -> str:
    return json.dumps(_notification(ts=ts, method="session/update", params={"sessionId": "s", "update": update}))


def _prompt(ts: str, text: str = "hello") -> str:
    return json.dumps(
        _notification(
            ts=ts,
            method="session/prompt",
            params={"sessionId": "s", "prompt": [{"type": "text", "text": text}]},
        )
    )


def _end_turn(ts: str, usage: dict) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": ts,
            "notification": {
                "jsonrpc": "2.0",
                "result": {"stopReason": "end_turn", "usage": usage},
            },
        }
    )


def _tool_call_start(ts: str, call_id: str, name: str) -> str:
    return _session_update(
        ts,
        {
            "sessionUpdate": "tool_call",
            "toolCallId": call_id,
            "status": "pending",
            "rawInput": {},
            "title": name,
            "_meta": {"claudeCode": {"toolName": name}},
        },
    )


def _tool_call_input(ts: str, call_id: str, raw_input: dict) -> str:
    return _session_update(
        ts,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": None,
            "rawInput": raw_input,
        },
    )


def _tool_call_completed(ts: str, call_id: str, output: str) -> str:
    return _session_update(
        ts,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": "completed",
            "rawOutput": output,
        },
    )


def _agent_text(ts: str, text: str) -> str:
    return _session_update(
        ts,
        {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}},
    )


def _error(ts: str, message: str) -> str:
    return json.dumps(_notification(ts=ts, method="_posthog/error", params={"message": message}))


def _join(lines: list[str]) -> str:
    return "\n".join(lines)


class TestSandboxedTraceCaptureParser(BaseTest):
    def test_single_turn_text_response(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z", text="hi"),
                _agent_text("2026-04-15T10:00:01.000Z", "hello back"),
                _end_turn(
                    "2026-04-15T10:00:02.000Z",
                    {
                        "inputTokens": 10,
                        "outputTokens": 20,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 30,
                    },
                ),
            ]
        )

        parsed = parse_log(raw, initial_prompt="hi")

        assert len(parsed.generations) == 1
        gen = parsed.generations[0]
        assert gen.input_messages == [{"role": "user", "content": "hi"}]
        assert gen.output_content == [{"type": "text", "text": "hello back"}]
        assert gen.token_usage["inputTokens"] == 10
        assert gen.token_usage["outputTokens"] == 20
        assert gen.start_ts == "2026-04-15T10:00:00.000Z"
        assert gen.end_ts == "2026-04-15T10:00:01.000Z"

    def test_tool_call_input_is_patched_from_followup_update(self):
        """The initial ``tool_call`` event has ``rawInput={}``; real arguments
        arrive in a subsequent ``tool_call_update``. The parser must patch the
        matching ``tool_use`` block so ``$ai_output_choices`` carries real args.
        """
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "toolu_1", "MyTool"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "toolu_1", {"q": "hello", "limit": 5}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "toolu_1", "ok"),
                _agent_text("2026-04-15T10:00:03.000Z", "done"),
                _end_turn(
                    "2026-04-15T10:00:04.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw)

        tool_use_blocks = [b for gen in parsed.generations for b in gen.output_content if b.get("type") == "tool_use"]
        assert len(tool_use_blocks) == 1
        assert tool_use_blocks[0]["name"] == "MyTool"
        assert tool_use_blocks[0]["input"] == {"q": "hello", "limit": 5}
        assert tool_use_blocks[0]["id"] == "toolu_1"

    def test_back_to_back_tool_calls_produce_separate_generations(self):
        """Regression test: the parser must flush on ``tool_call`` when
        ``pending_tool_results`` is non-empty. Three back-to-back tool calls
        without intervening ``agent_message`` events represent three distinct
        model calls, so ``parse_log`` should emit three generations.
        """
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                # turn 1: first tool call
                _tool_call_start("2026-04-15T10:00:01.000Z", "tool_a", "ToolA"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "tool_a", {"x": 1}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "tool_a", "result a"),
                # turn 2: second tool call (no agent text in between)
                _tool_call_start("2026-04-15T10:00:03.000Z", "tool_b", "ToolB"),
                _tool_call_input("2026-04-15T10:00:03.100Z", "tool_b", {"y": 2}),
                _tool_call_completed("2026-04-15T10:00:04.000Z", "tool_b", "result b"),
                # turn 3: final text reply
                _agent_text("2026-04-15T10:00:05.000Z", "final answer"),
                _end_turn(
                    "2026-04-15T10:00:06.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw, initial_prompt="hello")

        assert len(parsed.generations) == 3
        assert [len(g.output_content) for g in parsed.generations] == [1, 1, 1]

        # Each generation's start_ts comes from the previous boundary:
        #   gen[0] starts at session/prompt
        #   gen[1] starts when tool_a completed
        #   gen[2] starts when tool_b completed
        assert parsed.generations[0].start_ts == "2026-04-15T10:00:00.000Z"
        assert parsed.generations[1].start_ts == "2026-04-15T10:00:02.000Z"
        assert parsed.generations[2].start_ts == "2026-04-15T10:00:04.000Z"

        # Each generation ends when its last output block arrived
        assert parsed.generations[0].end_ts == "2026-04-15T10:00:01.000Z"
        assert parsed.generations[1].end_ts == "2026-04-15T10:00:03.000Z"
        assert parsed.generations[2].end_ts == "2026-04-15T10:00:05.000Z"

        # History growth: gen[1] sees the user prompt + assistant tool_a + tool_result a
        gen1_input = parsed.generations[1].input_messages
        assert gen1_input[0] == {"role": "user", "content": "hello"}
        assert gen1_input[1]["role"] == "assistant"
        assert gen1_input[1]["content"][0]["name"] == "ToolA"
        assert gen1_input[2]["role"] == "user"
        assert gen1_input[2]["content"][0]["type"] == "tool_result"
        assert gen1_input[2]["content"][0]["tool_use_id"] == "tool_a"

    def test_tool_results_become_user_message_in_next_generation_input(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "Search"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {"q": "foo"}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "t1", "payload"),
                _agent_text("2026-04-15T10:00:03.000Z", "answer"),
                _end_turn(
                    "2026-04-15T10:00:04.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw, initial_prompt="hi")

        assert len(parsed.generations) == 2
        second_gen_input = parsed.generations[1].input_messages
        assert len(second_gen_input) == 3
        tool_result_msg = second_gen_input[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "t1"
        assert "payload" in tool_result_msg["content"][0]["content"]

    def test_token_usage_attached_to_generation_that_saw_end_turn(self):
        """The agent-server emits one ``usage`` block per session at end_turn.
        It lands on the final generation only — this documents current behavior.
        """
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "Search"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {"q": "x"}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "t1", "r"),
                _agent_text("2026-04-15T10:00:03.000Z", "done"),
                _end_turn(
                    "2026-04-15T10:00:04.000Z",
                    {
                        "inputTokens": 5,
                        "outputTokens": 100,
                        "cachedReadTokens": 200,
                        "cachedWriteTokens": 50,
                        "totalTokens": 355,
                    },
                ),
            ]
        )

        parsed = parse_log(raw)

        assert len(parsed.generations) == 2
        assert parsed.generations[0].token_usage == {}
        assert parsed.generations[1].token_usage == {
            "inputTokens": 5,
            "outputTokens": 100,
            "cachedReadTokens": 200,
            "cachedWriteTokens": 50,
            "totalTokens": 355,
        }
        assert parsed.total_token_usage["totalTokens"] == 355

    def test_error_span_captured(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _agent_text("2026-04-15T10:00:01.000Z", "fine"),
                _error("2026-04-15T10:00:01.500Z", "something exploded"),
                _end_turn(
                    "2026-04-15T10:00:02.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw)

        error_spans = [s for s in parsed.spans if s.span_name == "error"]
        assert len(error_spans) == 1
        assert "something exploded" in error_spans[0].content

    def test_messages_property_reconstructs_final_assistant_turn(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _agent_text("2026-04-15T10:00:01.000Z", "hi!"),
                _end_turn(
                    "2026-04-15T10:00:02.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw, initial_prompt="hi")
        msgs = parsed.messages

        assert msgs[0] == {"role": "user", "content": "hi"}
        assert msgs[-1] == {"role": "assistant", "content": [{"type": "text", "text": "hi!"}]}

    def test_unknown_json_lines_are_skipped(self):
        raw = _join(
            [
                "not json at all",
                "{broken",
                _prompt("2026-04-15T10:00:00.000Z"),
                _agent_text("2026-04-15T10:00:01.000Z", "ok"),
                _end_turn(
                    "2026-04-15T10:00:02.000Z",
                    {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                ),
            ]
        )

        parsed = parse_log(raw)

        assert len(parsed.generations) == 1
        assert parsed.generations[0].output_content == [{"type": "text", "text": "ok"}]

    def test_empty_log_returns_no_generations(self):
        parsed = parse_log("")
        assert parsed.generations == []
        assert parsed.spans == []
