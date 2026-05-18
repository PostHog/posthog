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
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"model": "claude-opus-4-7"}}),
            ],
            "claude-opus-4-7",
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
                _line({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"model": "claude-opus-4-7"}}),
                _line(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"sessionId": "s1", "models": {"currentModelId": "claude-sonnet-4-6"}},
                    }
                ),
            ],
            "claude-opus-4-7",
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
