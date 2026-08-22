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

  it("keeps inline Pi images on the rendered user message", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "user_message",
          id: "user-1",
          timestamp: 1,
          content: [
            { type: "text", text: "What is this?" },
            {
              type: "image",
              data: "aW1hZ2U=",
              mimeType: "image/png",
              fileName: "screenshot.png",
            },
          ],
        },
      ],
      false,
    );

    expect(result.items[0]).toMatchObject({
      type: "user_message",
      content: "What is this?",
      attachments: [
        {
          id: expect.stringMatching(/^inline-image:/),
          label: "screenshot.png",
          previewUrl: "data:image/png;base64,aW1hZ2U=",
        },
      ],
    });
  });

  it("keeps generic extension tool result content for rendering", () => {
    const rawOutput = [{ type: "text", text: "Workflow finished" }];
    const result = buildAgentConversationItems(
      [
        {
          type: "tool_call_started",
          timestamp: 1,
          toolCall: {
            id: "workflow-1",
            title: "workflow",
            kind: null,
            status: "pending",
            rawInput: { name: "release" },
          },
        },
        {
          type: "tool_call_updated",
          timestamp: 2,
          toolCall: {
            id: "workflow-1",
            status: "completed",
            rawOutput,
            content: [
              {
                type: "content",
                content: { type: "text", text: "Workflow finished" },
              },
            ],
          },
        },
      ],
      false,
    );

    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: expect.objectContaining({
          sessionUpdate: "tool_call",
          toolCallId: "workflow-1",
          title: "workflow",
          status: "completed",
          rawOutput,
          content: [
            {
              type: "content",
              content: { type: "text", text: "Workflow finished" },
            },
          ],
        }),
      }),
    );
  });

  it("groups runtime-neutral provisioning progress", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "progress",
          timestamp: 1,
          step: "sandbox",
          status: "completed",
          label: "Set up sandbox",
          group: "setup:run-1",
        },
        {
          type: "progress",
          timestamp: 2,
          step: "clone",
          status: "in_progress",
          label: "Cloning repository",
          group: "setup:run-1",
          detail: "posthog/code",
        },
      ],
      true,
    );

    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: {
          sessionUpdate: "progress_group",
          isActive: true,
          steps: [
            {
              key: "sandbox",
              status: "completed",
              label: "Set up sandbox",
              detail: undefined,
            },
            {
              key: "clone",
              status: "in_progress",
              label: "Cloning repository",
              detail: "posthog/code",
            },
          ],
        },
      }),
    );
  });

  it("settles a completed runtime-neutral agent step", () => {
    const result = buildAgentConversationItems(
      [
        {
          type: "progress",
          timestamp: 1,
          step: "agent",
          status: "in_progress",
          label: "Starting agent",
          group: "setup:run-1",
        },
        {
          type: "progress",
          timestamp: 2,
          step: "agent",
          status: "completed",
          label: "Started agent",
          group: "setup:run-1",
        },
      ],
      true,
    );

    expect(result.items).toContainEqual(
      expect.objectContaining({
        type: "session_update",
        update: {
          sessionUpdate: "progress_group",
          isActive: false,
          steps: [
            {
              key: "agent",
              status: "completed",
              label: "Started agent",
              detail: undefined,
            },
          ],
        },
      }),
    );
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
