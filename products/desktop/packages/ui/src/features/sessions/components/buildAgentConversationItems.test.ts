import type { AgentConversationEvent } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { buildAgentConversationItems } from "./buildConversationItems";

describe("buildAgentConversationItems", () => {
  it("builds a turn with generic assistant and tool events", () => {
    const events: AgentConversationEvent[] = [
      {
        type: "user_message",
        id: "user-1",
        timestamp: 1,
        content: [{ type: "text", text: "Change the file" }],
      },
      {
        type: "assistant_message_chunk",
        timestamp: 2,
        content: { type: "text", text: "I will update it." },
      },
      {
        type: "tool_call_started",
        timestamp: 3,
        toolCall: {
          id: "edit-1",
          title: "edit",
          kind: "edit",
          status: "pending",
          rawInput: { path: "src/a.ts" },
        },
      },
      {
        type: "tool_call_updated",
        timestamp: 4,
        toolCall: {
          id: "edit-1",
          status: "completed",
          locations: [{ path: "src/a.ts", line: 1 }],
          content: [
            {
              type: "diff",
              path: "src/a.ts",
              oldText: "old",
              newText: "new",
            },
          ],
        },
      },
      { type: "turn_completed", timestamp: 5, stopReason: "stop" },
    ];

    const result = buildAgentConversationItems(events, false);
    const userMessage = result.items.find(
      (item) => item.type === "user_message",
    );
    const toolItem = result.items.find(
      (item) =>
        item.type === "session_update" &&
        item.update.sessionUpdate === "tool_call",
    );

    expect(userMessage).toMatchObject({
      type: "user_message",
      content: "Change the file",
    });
    expect(toolItem).toMatchObject({
      type: "session_update",
      update: {
        toolCallId: "edit-1",
        kind: "edit",
        status: "completed",
        locations: [{ path: "src/a.ts", line: 1 }],
        content: [
          {
            type: "diff",
            path: "src/a.ts",
            oldText: "old",
            newText: "new",
          },
        ],
      },
      turnContext: { turnComplete: true },
    });
    expect(result.completedToolCallCount).toBe(1);
    expect(result.lastTurnInfo).toMatchObject({
      isComplete: true,
      stopReason: "stop",
    });
  });

  it("builds and completes a generic compaction status", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "runtime_status",
          timestamp: 1,
          status: "compacting",
        },
        {
          type: "runtime_status",
          timestamp: 2,
          status: "compacting",
          isComplete: true,
        },
      ],
      false,
    );

    expect(result.isCompacting).toBe(false);
    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: expect.objectContaining({
          sessionUpdate: "status",
          status: "compacting",
          isComplete: true,
          startedAt: 1,
        }),
      }),
    );
  });

  it("builds a generic compaction failure status", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "runtime_status",
          timestamp: 1,
          status: "compacting",
        },
        {
          type: "runtime_status",
          timestamp: 2,
          status: "compacting_failed",
          error: "Not enough messages",
        },
      ],
      false,
    );

    expect(result.isCompacting).toBe(false);
    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: expect.objectContaining({
          sessionUpdate: "status",
          status: "compacting_failed",
          error: "Not enough messages",
        }),
      }),
    );
  });

  it("builds retry status and deduplicates runtime errors", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "runtime_status",
          timestamp: 1,
          status: "retrying",
          message: "Rate limited",
          attempt: 1,
          maxAttempts: 3,
          delayMs: 1000,
        },
        {
          type: "runtime_status",
          timestamp: 2,
          status: "retrying",
          isComplete: true,
        },
        {
          type: "runtime_error",
          timestamp: 3,
          errorType: "pi_runtime",
          message: "Rate limited",
        },
        {
          type: "runtime_error",
          timestamp: 4,
          errorType: "pi_runtime",
          message: "Rate limited",
        },
      ],
      false,
    );

    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: expect.objectContaining({
          sessionUpdate: "status",
          status: "retrying",
          isComplete: true,
          attempt: 1,
          maxAttempts: 3,
          delayMs: 1000,
        }),
      }),
    );
    expect(
      result.items.filter(
        (item) =>
          item.type === "session_update" &&
          item.update.sessionUpdate === "error",
      ),
    ).toHaveLength(1);
  });
});
