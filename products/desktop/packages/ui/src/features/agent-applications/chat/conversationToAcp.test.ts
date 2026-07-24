import type {
  SessionNotification,
  SessionUpdate,
} from "@agentclientprotocol/sdk";
import type {
  AcpMessage,
  JsonRpcNotification,
  JsonRpcRequest,
} from "@posthog/shared";
import type { AgentConversationMessage } from "@posthog/shared/agent-platform-types";
import { describe, expect, it } from "vitest";
import {
  conversationToAcpMessages,
  userMessageText,
} from "./conversationToAcp";

function methodOf(m: AcpMessage): string | undefined {
  return "method" in m.message ? m.message.method : undefined;
}

function updateOf(m: AcpMessage): SessionUpdate {
  const params = (m.message as JsonRpcNotification)
    .params as SessionNotification;
  return params.update;
}

describe("conversationToAcpMessages", () => {
  it("maps a single user→assistant turn to prompt + text chunk + turn_complete", () => {
    const convo: AgentConversationMessage[] = [
      { role: "user", content: "hello there", timestamp: 1000 },
      {
        role: "assistant",
        content: [{ type: "text", text: "hi back" }],
        timestamp: 2000,
      },
    ];

    const out = conversationToAcpMessages(convo);

    expect(out.map(methodOf)).toEqual([
      "session/prompt",
      "session/update",
      "_posthog/turn_complete",
    ]);
    const prompt = out[0].message as JsonRpcRequest<{
      prompt: { type: string; text: string }[];
    }>;
    expect(prompt.id).toBe(1);
    expect(prompt.params?.prompt[0]).toEqual({
      type: "text",
      text: "hello there",
    });
    expect(updateOf(out[1])).toEqual({
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: "hi back" },
    });
  });

  it("emits thinking as an agent_thought_chunk", () => {
    const out = conversationToAcpMessages([
      { role: "user", content: "think", timestamp: 1 },
      {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "hmm" },
          { type: "text", text: "answer" },
        ],
        timestamp: 2,
      },
    ]);
    expect(updateOf(out[1])).toEqual({
      sessionUpdate: "agent_thought_chunk",
      content: { type: "text", text: "hmm" },
    });
    expect(updateOf(out[2]).sessionUpdate).toBe("agent_message_chunk");
  });

  it("maps a tool call + its result onto the same toolCallId", () => {
    const out = conversationToAcpMessages([
      { role: "user", content: "run it", timestamp: 1 },
      {
        role: "assistant",
        content: [
          {
            type: "toolCall",
            id: "call_1",
            name: "@posthog/query",
            arguments: { sql: "select 1" },
          },
        ],
        timestamp: 2,
      },
      {
        role: "toolResult",
        toolCallId: "call_1",
        toolName: "@posthog/query",
        content: [{ type: "text", text: "42" }],
        isError: false,
        timestamp: 3,
      },
    ]);

    const call = updateOf(out[1]);
    expect(call).toMatchObject({
      sessionUpdate: "tool_call",
      toolCallId: "call_1",
      title: "@posthog/query",
      rawInput: { sql: "select 1" },
    });
    // No premature status on the call itself.
    expect("status" in call).toBe(false);

    const result = updateOf(out[2]);
    expect(result).toMatchObject({
      sessionUpdate: "tool_call_update",
      toolCallId: "call_1",
      status: "completed",
      content: [{ type: "content", content: { type: "text", text: "42" } }],
    });
  });

  it("marks an errored tool result as failed", () => {
    const out = conversationToAcpMessages([
      { role: "user", content: "x", timestamp: 1 },
      {
        role: "assistant",
        content: [{ type: "toolCall", id: "c1", name: "t", arguments: {} }],
        timestamp: 2,
      },
      {
        role: "toolResult",
        toolCallId: "c1",
        toolName: "t",
        content: [{ type: "text", text: "boom" }],
        isError: true,
        timestamp: 3,
      },
    ]);
    expect(updateOf(out[2])).toMatchObject({ status: "failed" });
  });

  it("closes the prior turn before each new user prompt and gives unique ids", () => {
    const out = conversationToAcpMessages([
      { role: "user", content: "first", timestamp: 1 },
      {
        role: "assistant",
        content: [{ type: "text", text: "a" }],
        timestamp: 2,
      },
      { role: "user", content: "second", timestamp: 3 },
      {
        role: "assistant",
        content: [{ type: "text", text: "b" }],
        timestamp: 4,
      },
    ]);

    expect(out.map(methodOf)).toEqual([
      "session/prompt",
      "session/update",
      "_posthog/turn_complete",
      "session/prompt",
      "session/update",
      "_posthog/turn_complete",
    ]);
    expect((out[0].message as JsonRpcRequest).id).toBe(1);
    expect((out[3].message as JsonRpcRequest).id).toBe(2);
  });

  it("returns nothing for an empty conversation", () => {
    expect(conversationToAcpMessages([])).toEqual([]);
  });

  it("flattens array-form user content", () => {
    expect(
      userMessageText([
        { type: "text", text: "a" },
        { type: "image", url: "x" },
        { type: "text", text: "b" },
      ]),
    ).toBe("ab");
    expect(userMessageText("plain")).toBe("plain");
  });
});
