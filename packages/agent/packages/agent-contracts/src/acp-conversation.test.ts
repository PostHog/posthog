import { describe, expect, it } from "vitest";
import {
  acpNotificationToAgentConversationEvent,
  agentConversationEventToAcpNotification,
} from "./acp-conversation";
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
          messageId: "u1",
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

describe("acpNotificationToAgentConversationEvent", () => {
  it.each<{ caseName: string; event: AgentConversationEvent }>([
    {
      caseName: "a user message",
      event: {
        type: "user_message",
        id: "u1",
        timestamp: 1000,
        content: [{ type: "text", text: "hi" }],
      },
    },
    {
      caseName: "a message chunk",
      event: {
        type: "assistant_message_chunk",
        timestamp: 1000,
        content: { type: "text", text: "yo" },
      },
    },
    {
      caseName: "a reasoning chunk",
      event: {
        type: "assistant_thought_chunk",
        timestamp: 1000,
        content: { type: "text", text: "hm" },
      },
    },
    {
      caseName: "a user shell command",
      event: {
        type: "tool_call_started",
        timestamp: 1000,
        toolCall: {
          id: "pi-bash-1",
          title: "ls",
          kind: "execute",
          rawInput: { command: "ls" },
          origin: "user_shell",
        },
      },
    },
    {
      caseName: "a tool start with tool meta",
      event: {
        type: "tool_call_started",
        timestamp: 1000,
        toolCall: {
          id: "t1",
          title: "read",
          kind: "read",
          status: "pending",
          locations: [{ path: "a.ts" }],
          _meta: { posthog: { toolName: "Read" } },
        },
      },
    },
    {
      caseName: "a subagent tool update with tool meta",
      event: {
        type: "tool_call_updated",
        timestamp: 1000,
        toolCall: {
          id: "t2",
          parentId: "t1",
          status: "completed",
          _meta: { posthog: { toolName: "Read" } },
        },
      },
    },
    {
      caseName: "a subagent tool update without tool meta",
      event: {
        type: "tool_call_updated",
        timestamp: 1000,
        toolCall: { id: "t3", parentId: "t1", status: "failed" },
      },
    },
    {
      caseName: "a progress step",
      event: {
        type: "progress",
        timestamp: 1000,
        step: "clone",
        status: "completed",
        label: "Cloning",
        group: "setup",
        detail: "posthog/posthog",
      },
    },
    {
      caseName: "a retry status",
      event: {
        type: "runtime_status",
        timestamp: 1000,
        status: "retrying",
        isComplete: false,
        message: "Rate limited",
        attempt: 2,
        maxAttempts: 5,
        delayMs: 4000,
      },
    },
    {
      caseName: "a runtime error",
      event: {
        type: "runtime_error",
        timestamp: 1000,
        errorType: "pi_runtime",
        message: "boom",
      },
    },
    {
      caseName: "a turn end with usage",
      event: {
        type: "turn_completed",
        timestamp: 1000,
        stopReason: "end_turn",
        totalTokens: 6,
        usage: {
          inputTokens: 5,
          outputTokens: 1,
          cachedReadTokens: 0,
          cachedWriteTokens: 0,
          totalTokens: 6,
          contextTokens: 6,
          contextWindow: 200000,
        },
      },
    },
    {
      caseName: "a queue update",
      event: {
        type: "queue_update",
        timestamp: 1000,
        steering: ["stop"],
        followUp: [],
      },
    },
  ])("restores $caseName from its ACP form", ({ event }) => {
    const notification = agentConversationEventToAcpNotification(event);
    expect(notification).not.toBeNull();
    expect(
      acpNotificationToAgentConversationEvent(
        notification as NonNullable<typeof notification>,
        event.timestamp,
      ),
    ).toEqual(event);
  });

  it("reads a whole agent message as one message chunk", () => {
    expect(
      acpNotificationToAgentConversationEvent(
        {
          method: "session/update",
          params: {
            update: {
              sessionUpdate: "agent_message",
              content: { type: "text", text: "pong" },
            },
          },
        },
        1000,
      ),
    ).toEqual({
      type: "assistant_message_chunk",
      timestamp: 1000,
      content: { type: "text", text: "pong" },
    });
  });

  it("restores a tool title the sender dropped because it repeated the tool name", () => {
    expect(
      acpNotificationToAgentConversationEvent(
        {
          method: "session/update",
          params: {
            update: {
              sessionUpdate: "tool_call",
              toolCallId: "t1",
              name: "read",
              kind: "read",
            },
          },
        },
        1000,
      ),
    ).toEqual({
      type: "tool_call_started",
      timestamp: 1000,
      toolCall: { id: "t1", name: "read", title: "read", kind: "read" },
    });
  });

  it.each([
    {
      caseName: "a notification a Pi extension message produced",
      notification: {
        method: "_posthog/status",
        params: {
          status: "extension_notice",
          isComplete: true,
          message: "lint.ts failed: boom",
          _meta: { piExtension: { type: "extension_error", error: "boom" } },
        },
      },
    },
    {
      caseName: "a usage update",
      notification: {
        method: "_posthog/usage_update",
        params: { used: { inputTokens: 5 } },
      },
    },
  ])("maps $caseName to no conversation event", ({ notification }) => {
    expect(acpNotificationToAgentConversationEvent(notification, 1000)).toBe(
      null,
    );
  });
});
