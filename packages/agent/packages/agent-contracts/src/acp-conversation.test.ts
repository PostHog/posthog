import { describe, expect, it } from "vitest";
import { agentConversationEventToAcpNotification } from "./acp-conversation";
import type { AgentConversationEvent } from "./agent-conversation";

describe("agentConversationEventToAcpNotification", () => {
  it.each<{
    caseName: string;
    event: AgentConversationEvent;
    expected: unknown;
  }>([
    {
      caseName: "a user message with an attachment",
      event: {
        type: "user_message",
        id: "u1",
        timestamp: 1,
        content: [
          { type: "text", text: "Check this" },
          {
            type: "resource_link",
            uri: "file:///w/.posthog/attachments/run/a/notes.md",
            name: "notes.md",
          },
        ],
      },
      expected: {
        method: "_posthog/user_message",
        params: {
          content: [
            { type: "text", text: "Check this" },
            {
              type: "resource_link",
              uri: "file:///w/.posthog/attachments/run/a/notes.md",
              name: "notes.md",
            },
          ],
        },
      },
    },
    {
      caseName: "a reasoning chunk",
      event: {
        type: "assistant_thought_chunk",
        timestamp: 1,
        content: { type: "text", text: "hm" },
      },
      expected: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "agent_thought_chunk",
            content: { type: "text", text: "hm" },
          },
        },
      },
    },
    {
      caseName: "a tool start, keeping its title and tool meta",
      event: {
        type: "tool_call_started",
        timestamp: 1,
        toolCall: {
          id: "t1",
          title: "read",
          kind: "read",
          status: "pending",
          rawInput: { path: "a.ts" },
          locations: [{ path: "a.ts" }],
          _meta: { posthog: { toolName: "Read" } },
        },
      },
      expected: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call",
            toolCallId: "t1",
            title: "read",
            kind: "read",
            status: "pending",
            rawInput: { path: "a.ts" },
            locations: [{ path: "a.ts" }],
            _meta: { posthog: { toolName: "Read" } },
          },
        },
      },
    },
    {
      caseName:
        "a subagent tool update, adding its parent without losing the tool meta",
      event: {
        type: "tool_call_updated",
        timestamp: 1,
        toolCall: {
          id: "t2",
          parentId: "t1",
          status: "completed",
          _meta: { posthog: { toolName: "Read" } },
        },
      },
      expected: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call_update",
            toolCallId: "t2",
            status: "completed",
            _meta: {
              posthog: { toolName: "Read" },
              claudeCode: { parentToolCallId: "t1" },
            },
          },
        },
      },
    },
    {
      caseName: "a tool update without an id",
      event: {
        type: "tool_call_updated",
        timestamp: 1,
        toolCall: { id: "" },
      },
      expected: null,
    },
    {
      caseName: "a turn end from a log that still says aborted",
      event: { type: "turn_completed", timestamp: 1, stopReason: "aborted" },
      expected: {
        method: "_posthog/turn_complete",
        params: { stopReason: "cancelled" },
      },
    },
    {
      caseName: "a turn end with usage",
      event: {
        type: "turn_completed",
        timestamp: 1,
        stopReason: "end_turn",
        usage: {
          inputTokens: 5,
          outputTokens: 1,
          cachedReadTokens: 0,
          cachedWriteTokens: 0,
          totalTokens: 6,
        },
      },
      expected: {
        method: "_posthog/turn_complete",
        params: {
          stopReason: "end_turn",
          usage: {
            inputTokens: 5,
            outputTokens: 1,
            cachedReadTokens: 0,
            cachedWriteTokens: 0,
            totalTokens: 6,
          },
        },
      },
    },
    {
      caseName: "a runtime error",
      event: {
        type: "runtime_error",
        timestamp: 1,
        errorType: "pi_runtime",
        message: "boom",
      },
      expected: {
        method: "_posthog/error",
        params: { message: "boom", errorType: "pi_runtime" },
      },
    },
    {
      caseName: "a retry status",
      event: { type: "runtime_status", timestamp: 1, status: "retrying" },
      expected: {
        method: "_posthog/status",
        params: { status: "retrying", isComplete: false },
      },
    },
  ])("maps $caseName", ({ event, expected }) => {
    expect(agentConversationEventToAcpNotification(event)).toEqual(expected);
  });
});
