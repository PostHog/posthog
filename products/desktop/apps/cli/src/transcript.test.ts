import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import { projectTranscriptEvent } from "./transcript.js";

function event(value: unknown): AgentSessionEvent {
  return value as AgentSessionEvent;
}

describe("projectTranscriptEvent", () => {
  it("keeps streamed assistant text when the completed message contains the same text", () => {
    const transcript = [
      event({
        type: "message_update",
        message: { timestamp: 1 },
        assistantMessageEvent: { type: "text_delta", delta: "Hello" },
      }),
      event({
        type: "message_end",
        message: {
          role: "assistant",
          timestamp: 1,
          content: [{ type: "text", text: "Hello" }],
        },
      }),
    ].reduce(projectTranscriptEvent, []);

    expect(transcript).toEqual([
      { id: "assistant-1", kind: "assistant", text: "Hello" },
    ]);
  });

  it("updates the matching tool when parallel tools finish out of order", () => {
    const transcript = [
      event({
        type: "tool_execution_start",
        toolCallId: "read",
        toolName: "read",
      }),
      event({
        type: "tool_execution_start",
        toolCallId: "grep",
        toolName: "grep",
      }),
      event({
        type: "tool_execution_end",
        toolCallId: "grep",
        toolName: "grep",
        isError: false,
      }),
    ].reduce(projectTranscriptEvent, []);

    expect(transcript).toEqual([
      { id: "tool-read", kind: "tool", name: "read", state: "running" },
      { id: "tool-grep", kind: "tool", name: "grep", state: "completed" },
    ]);
  });
});
