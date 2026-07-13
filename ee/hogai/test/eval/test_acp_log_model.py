from __future__ import annotations

import json

import pytest

from ee.hogai.eval.sandboxed.acp_log import parse_log


def _line(payload: dict) -> str:
    return json.dumps({"type": "notification", "timestamp": "2026-04-29T08:42:29.620Z", "notification": payload})


@pytest.mark.parametrize(
    "lines, expected_model",
    [
        pytest.param(
            [
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "session/new",
                        "params": {"model": "anthropic/claude-opus-4-7"},
                    }
                ),
            ],
            "anthropic/claude-opus-4-7",
            id="captures_from_session_new_params",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": "/tmp"}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-sonnet-4-6"}},
                    }
                ),
            ],
            "claude-sonnet-4-6",
            id="falls_back_to_result_currentModelId",
        ),
        pytest.param(
            [
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "session/new",
                        "params": {"model": "anthropic/claude-opus-4-7"},
                    }
                ),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-sonnet-4-6"}},
                    }
                ),
            ],
            "anthropic/claude-opus-4-7",
            id="prefers_params_over_result_when_both_present",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/prompt", "params": {}}),
            ],
            "",
            id="empty_when_no_session_new",
        ),
        pytest.param(
            [
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"model": ""}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-haiku-4-5"}},
                    }
                ),
            ],
            "claude-haiku-4-5",
            id="ignores_empty_string_model_and_falls_back",
        ),
    ],
)
def test_parse_log_extracts_agent_model(lines: list[str], expected_model: str) -> None:
    parsed = parse_log("\n".join(lines))
    assert parsed.model == expected_model


def _tool_call_line(meta: dict | None, title: str) -> str:
    return _line(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "t1",
                    "title": title,
                    "_meta": meta,
                    "rawInput": {},
                }
            },
        }
    )


@pytest.mark.parametrize(
    "meta, title, expected_name",
    [
        pytest.param(
            {"claudeCode": {"toolName": "mcp__posthog__execute_sql"}},
            "execute sql",
            "mcp__posthog__execute_sql",
            id="claude_runtime_meta",
        ),
        pytest.param(
            {"posthog": {"toolName": "mcp__posthog__exec", "mcp": {"server": "posthog", "tool": "exec"}}},
            "posthog/exec",
            "mcp__posthog__exec",
            id="codex_runtime_meta",
        ),
        pytest.param(None, "/bin/bash -lc ls", "/bin/bash -lc ls", id="null_meta_falls_back_to_title"),
        pytest.param({"posthog": {}}, "posthog/exec", "posthog/exec", id="empty_adapter_meta_falls_back_to_title"),
    ],
)
def test_parse_log_resolves_tool_name_from_runtime_meta(meta: dict | None, title: str, expected_name: str) -> None:
    parsed = parse_log(_tool_call_line(meta, title))
    tool_uses = [
        block
        for message in parsed.messages
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_use"
    ]
    assert [block["name"] for block in tool_uses] == [expected_name]
