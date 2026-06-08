"""Unit tests for the unified ACP log accessor used by sandboxed-eval scorers."""

from __future__ import annotations

import json

import unittest

from ee.hogai.eval.sandboxed.log_parser import (
    EXEC_TOOL_NAME,
    INFO_SYNTHETIC_PREFIX,
    SKILL_TOOL_NAME,
    LogParser,
    SkillCall,
    ToolCall,
    normalize_tool_name,
)


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


def _end_turn(ts: str, usage: dict | None = None) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": ts,
            "notification": {
                "jsonrpc": "2.0",
                "result": {
                    "stopReason": "end_turn",
                    "usage": usage
                    or {
                        "inputTokens": 1,
                        "outputTokens": 1,
                        "cachedReadTokens": 0,
                        "cachedWriteTokens": 0,
                        "totalTokens": 2,
                    },
                },
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


def _tool_call_completed(ts: str, call_id: str, output: str, status: str = "completed") -> str:
    return _session_update(
        ts,
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": call_id,
            "status": status,
            "rawOutput": output,
        },
    )


def _agent_text(ts: str, text: str) -> str:
    return _session_update(
        ts,
        {"sessionUpdate": "agent_message", "content": {"type": "text", "text": text}},
    )


def _join(lines: list[str]) -> str:
    return "\n".join(lines)


def _make_tool_log(
    tool_name: str,
    raw_input: dict,
    output: str = "ok",
    status: str = "completed",
    call_id: str = "t1",
) -> str:
    """Build a minimal one-call session: prompt → tool → final text → end_turn."""
    return _join(
        [
            _prompt("2026-04-15T10:00:00.000Z"),
            _tool_call_start("2026-04-15T10:00:01.000Z", call_id, tool_name),
            _tool_call_input("2026-04-15T10:00:01.100Z", call_id, raw_input),
            _tool_call_completed("2026-04-15T10:00:02.000Z", call_id, output, status=status),
            _agent_text("2026-04-15T10:00:03.000Z", "done"),
            _end_turn("2026-04-15T10:00:04.000Z"),
        ]
    )


class TestLogParserSkillCalls(unittest.TestCase):
    def test_was_skill_called_returns_true_for_matching_skill(self):
        raw = _make_tool_log(
            SKILL_TOOL_NAME,
            {"skill": "improving-drf-endpoints", "args": ""},
        )
        parser = LogParser(raw, initial_prompt="hi")
        assert parser.was_skill_called("improving-drf-endpoints")

    def test_was_skill_called_returns_false_for_unmatched_skill(self):
        raw = _make_tool_log(
            SKILL_TOOL_NAME,
            {"skill": "improving-drf-endpoints", "args": ""},
        )
        parser = LogParser(raw, initial_prompt="hi")
        assert not parser.was_skill_called("django-migrations")

    def test_was_skill_called_returns_false_when_no_skill_calls(self):
        raw = _make_tool_log("query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")
        assert not parser.was_skill_called("anything")

    def test_get_skill_calls_returns_chronological_list(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "s1", SKILL_TOOL_NAME),
                _tool_call_input("2026-04-15T10:00:01.100Z", "s1", {"skill": "first", "args": "a"}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "s1", "r1"),
                _tool_call_start("2026-04-15T10:00:03.000Z", "s2", SKILL_TOOL_NAME),
                _tool_call_input("2026-04-15T10:00:03.100Z", "s2", {"skill": "second"}),
                _tool_call_completed("2026-04-15T10:00:04.000Z", "s2", "r2"),
                _agent_text("2026-04-15T10:00:05.000Z", "done"),
                _end_turn("2026-04-15T10:00:06.000Z"),
            ]
        )

        parser = LogParser(raw, initial_prompt="hi")
        calls = parser.get_skill_calls()

        assert len(calls) == 2
        assert calls[0].name == "first"
        assert calls[0].args == "a"
        assert calls[0].output == "r1"
        assert not calls[0].is_error
        assert calls[1].name == "second"
        assert calls[1].args is None
        assert calls[0].position < calls[1].position

    def test_get_skill_calls_filters_by_name(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "s1", SKILL_TOOL_NAME),
                _tool_call_input("2026-04-15T10:00:01.100Z", "s1", {"skill": "first"}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "s1", "r1"),
                _tool_call_start("2026-04-15T10:00:03.000Z", "s2", SKILL_TOOL_NAME),
                _tool_call_input("2026-04-15T10:00:03.100Z", "s2", {"skill": "second"}),
                _tool_call_completed("2026-04-15T10:00:04.000Z", "s2", "r2"),
                _agent_text("2026-04-15T10:00:05.000Z", "done"),
                _end_turn("2026-04-15T10:00:06.000Z"),
            ]
        )

        parser = LogParser(raw, initial_prompt="hi")
        only_first = parser.get_skill_calls("first")

        assert len(only_first) == 1
        assert only_first[0].name == "first"

    def test_skill_calls_are_excluded_from_get_tool_calls(self):
        raw = _make_tool_log(SKILL_TOOL_NAME, {"skill": "x"})
        parser = LogParser(raw, initial_prompt="hi")

        assert parser.get_tool_calls() == []
        assert len(parser.get_skill_calls()) == 1


class TestLogParserToolCalls(unittest.TestCase):
    def test_regular_tool_call_returns_normalized_name_and_input(self):
        raw = _make_tool_log("query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        assert len(calls) == 1
        call = calls[0]
        assert call.name == "query-trends"
        assert call.input == {"foo": 1}
        assert call.output == "ok"
        assert not call.is_error
        assert not call.is_exec_unwrapped
        assert call.raw_name == "query-trends"

    def test_get_tool_calls_filters_by_normalized_name(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "query-trends"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {"a": 1}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "t1", "r1"),
                _tool_call_start("2026-04-15T10:00:03.000Z", "t2", "query-funnel"),
                _tool_call_input("2026-04-15T10:00:03.100Z", "t2", {"b": 2}),
                _tool_call_completed("2026-04-15T10:00:04.000Z", "t2", "r2"),
                _agent_text("2026-04-15T10:00:05.000Z", "done"),
                _end_turn("2026-04-15T10:00:06.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        trends = parser.get_tool_calls("query-trends")
        funnels = parser.get_tool_calls("query-funnel")

        assert len(trends) == 1
        assert trends[0].input == {"a": 1}
        assert len(funnels) == 1
        assert funnels[0].input == {"b": 2}

    def test_failed_tool_calls_surface_with_is_error_true(self):
        raw = _make_tool_log("query-trends", {"foo": 1}, output="boom", status="failed")
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        assert len(calls) == 1
        assert calls[0].is_error
        assert calls[0].output == "boom"

    def test_unpaired_tool_use_surfaces_with_is_error_true_and_empty_output(self):
        """When tool_call starts but no completion update arrives, the parser
        emits a ``tool_use`` block with no matching ``tool_result``. We surface
        it as ``is_error=True`` so downstream filters can drop it."""
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "query-trends"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {"foo": 1}),
                _agent_text("2026-04-15T10:00:03.000Z", "done"),
                _end_turn("2026-04-15T10:00:04.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        assert len(calls) == 1
        assert calls[0].is_error
        assert calls[0].output == ""

    def test_mcp_prefix_is_stripped_in_normalized_name(self):
        raw = _make_tool_log("mcp__posthog__query-trends", {"foo": 1})
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        assert call.name == "query-trends"
        assert call.raw_name == "mcp__posthog__query-trends"

    def test_exec_call_command_is_unwrapped(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": 'call query-retention {"foo": 1}'},
            output="results",
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        assert len(calls) == 1
        call = calls[0]
        assert call.name == "query-retention"
        assert call.input == {"foo": 1}
        assert call.is_exec_unwrapped
        assert call.raw_name == EXEC_TOOL_NAME
        assert call.output == "results"

    def test_exec_call_with_json_flag_is_unwrapped(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": 'call --json query-trends {"x": 2}'},
        )
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        assert call.name == "query-trends"
        assert call.input == {"x": 2}
        assert call.is_exec_unwrapped

    def test_exec_info_command_produces_synthetic_name(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": "info query-trends"},
        )
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        assert call.name == f"{INFO_SYNTHETIC_PREFIX}query-trends"
        assert call.input == {}
        assert call.is_exec_unwrapped

    def test_exec_unrecognized_command_falls_back_to_raw_exec(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": "search foo"},
        )
        parser = LogParser(raw, initial_prompt="hi")

        call = parser.get_tool_calls()[0]
        assert call.name == EXEC_TOOL_NAME
        assert not call.is_exec_unwrapped
        assert call.input == {"command": "search foo"}

    def test_filter_by_name_matches_exec_unwrapped_inner_tool(self):
        raw = _make_tool_log(
            EXEC_TOOL_NAME,
            {"command": 'call query-retention {"foo": 1}'},
        )
        parser = LogParser(raw, initial_prompt="hi")

        assert len(parser.get_tool_calls("query-retention")) == 1
        assert parser.get_tool_calls("exec") == []

    def test_position_is_chronological(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "first"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "t1", "r1"),
                _tool_call_start("2026-04-15T10:00:03.000Z", "t2", "second"),
                _tool_call_input("2026-04-15T10:00:03.100Z", "t2", {}),
                _tool_call_completed("2026-04-15T10:00:04.000Z", "t2", "r2"),
                _agent_text("2026-04-15T10:00:05.000Z", "done"),
                _end_turn("2026-04-15T10:00:06.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")

        calls = parser.get_tool_calls()
        assert [c.name for c in calls] == ["first", "second"]
        assert calls[0].position < calls[1].position


class TestLogParserMessages(unittest.TestCase):
    def test_get_final_agent_message_returns_last_assistant_text(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _agent_text("2026-04-15T10:00:01.000Z", "first reply"),
                _tool_call_start("2026-04-15T10:00:02.000Z", "t1", "search"),
                _tool_call_input("2026-04-15T10:00:02.100Z", "t1", {}),
                _tool_call_completed("2026-04-15T10:00:03.000Z", "t1", "r"),
                _agent_text("2026-04-15T10:00:04.000Z", "final reply"),
                _end_turn("2026-04-15T10:00:05.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")
        assert parser.get_final_agent_message() == "final reply"

    def test_get_final_agent_message_returns_none_when_run_ends_on_tool_use(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _tool_call_start("2026-04-15T10:00:01.000Z", "t1", "search"),
                _tool_call_input("2026-04-15T10:00:01.100Z", "t1", {}),
                _tool_call_completed("2026-04-15T10:00:02.000Z", "t1", "r"),
                _end_turn("2026-04-15T10:00:03.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="hi")
        assert parser.get_final_agent_message() is None

    def test_get_user_prompt_returns_initial_prompt_when_seeded(self):
        raw = _join(
            [
                _prompt("2026-04-15T10:00:00.000Z"),
                _agent_text("2026-04-15T10:00:01.000Z", "ok"),
                _end_turn("2026-04-15T10:00:02.000Z"),
            ]
        )
        parser = LogParser(raw, initial_prompt="seeded prompt")
        assert parser.get_user_prompt() == "seeded prompt"

    def test_get_user_prompt_falls_back_when_no_initial_prompt(self):
        raw = _join(
            [
                _agent_text("2026-04-15T10:00:01.000Z", "ok"),
                _end_turn("2026-04-15T10:00:02.000Z"),
            ]
        )
        parser = LogParser(raw)
        assert parser.get_user_prompt() == ""


class TestLogParserModels(unittest.TestCase):
    def test_tool_call_is_frozen(self):
        call = ToolCall(
            name="x",
            input={},
            output="",
            is_error=False,
            call_id="c",
            position=0,
            raw_name="x",
            is_exec_unwrapped=False,
        )
        with self.assertRaises(Exception):
            call.name = "y"  # type: ignore[misc]

    def test_skill_call_is_frozen(self):
        call = SkillCall(name="x", call_id="c", output="", is_error=False, position=0)
        with self.assertRaises(Exception):
            call.name = "y"  # type: ignore[misc]


class TestNormalizeToolName(unittest.TestCase):
    def test_strips_mcp_prefix(self):
        assert normalize_tool_name("mcp__posthog__query-trends") == "query-trends"

    def test_passes_through_bare_names(self):
        assert normalize_tool_name("query-trends") == "query-trends"

    def test_handles_empty_and_none(self):
        assert normalize_tool_name(None) == ""
        assert normalize_tool_name("") == ""
