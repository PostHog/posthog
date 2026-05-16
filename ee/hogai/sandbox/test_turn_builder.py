from ee.hogai.sandbox.turn_builder import SandboxTurnBuilder, build_human_message


def _evt(update: dict) -> dict:
    return {
        "type": "notification",
        "notification": {"method": "session/update", "params": {"update": update}},
    }


def test_agent_message_chunks_coalesce():
    builder = SandboxTurnBuilder()
    builder.feed(_evt({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hello"}}))
    builder.feed(_evt({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": " world"}}))
    messages = builder.finalize()
    assert len(messages) == 1
    assert messages[0]["type"] == "ai"
    assert messages[0]["content"] == "Hello world"
    assert messages[0]["id"].startswith("sandbox-")


def test_thought_then_message_emits_two_messages():
    builder = SandboxTurnBuilder()
    builder.feed(_evt({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "thinking…"}}))
    builder.feed(_evt({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "done"}}))
    messages = builder.finalize()
    assert [m["type"] for m in messages] == ["ai/reasoning", "ai"]
    assert messages[0]["content"] == "thinking…"
    assert messages[1]["content"] == "done"


def test_tool_call_lifecycle_produces_tool_message_with_updated_status():
    builder = SandboxTurnBuilder()
    builder.feed(_evt({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "calling"}}))
    builder.feed(
        _evt(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "t1",
                "title": "mcp__posthog__execute-sql",
                "rawInput": {"query": "SELECT 1"},
                "status": "pending",
            }
        )
    )
    builder.feed(
        _evt(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "t1",
                "status": "completed",
                "content": [{"type": "text", "text": "[[1]]"}],
                "rawOutput": {"rows": [[1]]},
            }
        )
    )
    builder.feed(_evt({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": " done"}}))
    messages = builder.finalize()

    # Expect: AssistantMessage("calling"), AssistantMessage(" done", tool_calls=[t1]), tool result
    types = [m["type"] for m in messages]
    assert types == ["ai", "ai", "tool"]

    tool_message = messages[-1]
    assert tool_message["tool_call_id"] == "t1"
    assert tool_message["ui_payload"]["_sandbox"] is True
    assert tool_message["ui_payload"]["status"] == "completed"
    assert tool_message["ui_payload"]["args"] == {"query": "SELECT 1"}
    assert tool_message["ui_payload"]["output"] == {"rows": [[1]]}


def test_ignores_non_session_update_events():
    builder = SandboxTurnBuilder()
    builder.feed({"type": "notification", "notification": {"method": "_posthog/turn_complete"}})
    builder.feed({"type": "result", "result": "anything"})
    assert builder.finalize() == []


def test_tool_call_missing_id_is_dropped():
    builder = SandboxTurnBuilder()
    builder.feed(_evt({"sessionUpdate": "tool_call", "title": "x"}))
    assert builder.finalize() == []


def test_build_human_message_has_human_type():
    msg = build_human_message("hi")
    assert msg["type"] == "human"
    assert msg["content"] == "hi"
    assert msg["id"]
