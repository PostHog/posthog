import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { classifyTurnEventKind, readTurnAgentText } from "./sessionService";

function update(
  sessionUpdate: string,
  content?: { type: string; text?: string },
): AcpMessage["message"] {
  return {
    jsonrpc: "2.0",
    method: "session/update",
    params: { update: { sessionUpdate, ...(content ? { content } : {}) } },
  } as AcpMessage["message"];
}

const AGENT_TEXT = { type: "text", text: "hello" };

describe("turn agent-text classification", () => {
  it.each([
    [
      "live agent_message_chunk",
      update("agent_message_chunk", AGENT_TEXT),
      "text",
      "hello",
    ],
    // SessionLogWriter coalesces a chunk run into one agent_message, so
    // hydration and cloud replay read the turn's text back as this final.
    [
      "hydrated agent_message",
      update("agent_message", AGENT_TEXT),
      "text",
      "hello",
    ],
    [
      "agent_thought_chunk",
      update("agent_thought_chunk", { type: "text", text: "thinking" }),
      "output",
      "",
    ],
    ["tool_call", update("tool_call"), "output", ""],
    [
      "non-text agent_message",
      update("agent_message", { type: "image" }),
      "output",
      "",
    ],
    [
      "user_message_chunk",
      update("user_message_chunk", { type: "text", text: "hi" }),
      "other",
      "",
    ],
  ] as const)("classifies %s", (_label, msg, kind, text) => {
    expect(classifyTurnEventKind(msg)).toBe(kind);
    expect(readTurnAgentText(msg)).toBe(text);
  });

  it("treats a turn response as neither text nor output", () => {
    const response = {
      jsonrpc: "2.0",
      id: 1,
      result: { stopReason: "end_turn" },
    } as AcpMessage["message"];
    expect(classifyTurnEventKind(response)).toBe("other");
    expect(readTurnAgentText(response)).toBe("");
  });
});
