import { makeAttachmentUri } from "@posthog/core/sessions/promptContent";
import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildConversationItems,
  type ConversationItem,
} from "./buildConversationItems";

function consoleMsg(ts: number, message: string, level = "info"): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/console",
      params: { level, message },
    },
  };
}

function progressMsg(
  ts: number,
  step: string,
  status: string,
  label: string,
  detail?: string,
  group = "setup",
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/progress",
      params: { step, status, label, detail, group },
    },
  };
}

function userPromptMsg(ts: number, id: number, text: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text }] },
    },
  };
}

function promptResponseMsg(ts: number, id: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      result: { stopReason: "end_turn" },
    },
  };
}

function turnCompleteMsg(ts: number, stopReason = "end_turn"): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/turn_complete",
      params: { sessionId: "session-1", stopReason },
    },
  };
}

function backgroundTurnCompleteMsg(
  ts: number,
  stopReason = "end_turn",
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/background_turn_complete",
      params: { sessionId: "session-1", stopReason },
    },
  };
}

function agentMessageMsg(ts: number, text: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  };
}

function resourcesUsedMsg(
  ts: number,
  products: { id: string; label: string }[],
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/resources_used",
      params: { sessionId: "session-1", products },
    },
  };
}

function usageUpdateMsg(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: { sessionUpdate: "usage_update", used: 100, size: 200_000 },
      },
    },
  };
}

function statusMsg(
  ts: number,
  status: string,
  isComplete?: boolean,
  error?: string,
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/status",
      params: { sessionId: "session-1", status, isComplete, error },
    },
  };
}

function refusalStatusMsg(
  ts: number,
  status: "refusal" | "refusal_fallback",
  fields: { explanation?: string; fromModel?: string; toModel?: string } = {},
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/status",
      params: { sessionId: "session-1", status, ...fields },
    },
  };
}

describe("buildConversationItems", () => {
  it("extracts cloud prompt attachments into user messages", () => {
    const uri = makeAttachmentUri("/tmp/hello world.txt");

    const events: AcpMessage[] = [
      {
        type: "acp_message",
        ts: 1,
        message: {
          jsonrpc: "2.0",
          id: 1,
          method: "session/prompt",
          params: {
            prompt: [
              { type: "text", text: "read this file" },
              {
                type: "resource",
                resource: {
                  uri,
                  text: "watup",
                  mimeType: "text/plain",
                },
              },
            ],
          },
        },
      },
    ];

    const result = buildConversationItems(events, null);

    expect(result.items).toEqual([
      {
        type: "user_message",
        id: "turn-1-1-user",
        content: "read this file",
        timestamp: 1,
        attachments: [
          {
            id: uri,
            label: "hello world.txt",
          },
        ],
      },
    ]);
  });

  it("clears the compacting spinner on a successful completion status, without duplicating the row", () => {
    // A successful compaction sends a terminal `status: compacting, isComplete:
    // true`. It must flip the existing status row, not append a second one.
    const result = buildConversationItems(
      [
        userPromptMsg(1, 1, "hi"),
        statusMsg(2, "compacting"),
        statusMsg(3, "compacting", true),
      ],
      null,
    );

    const statusItems = result.items.filter(
      (i): i is Extract<ConversationItem, { type: "session_update" }> =>
        i.type === "session_update" && i.update.sessionUpdate === "status",
    );
    expect(statusItems).toHaveLength(1);
    expect((statusItems[0].update as { isComplete?: boolean }).isComplete).toBe(
      true,
    );
    expect(result.isCompacting).toBe(false);
  });

  it("builds a compact boundary without optional metadata", () => {
    const result = buildConversationItems(
      [
        userPromptMsg(1, 1, "hi"),
        statusMsg(2, "compacting"),
        {
          type: "acp_message",
          ts: 3,
          message: {
            jsonrpc: "2.0",
            method: "_posthog/compact_boundary",
            params: { sessionId: "session-1" },
          },
        },
      ],
      null,
    );

    const boundary = result.items.find(
      (item) =>
        item.type === "session_update" &&
        item.update.sessionUpdate === "compact_boundary",
    );
    expect(boundary).toMatchObject({
      type: "session_update",
      update: { sessionUpdate: "compact_boundary" },
    });
    expect(result.isCompacting).toBe(false);
  });

  it("renders a failed compaction as a compacting_failed status row and clears the spinner", () => {
    // A failed compaction emits no compact_boundary, so the agent sends a
    // structured `compacting_failed` status: it clears the spinner (the original
    // compacting row goes complete) and adds the outcome row with the error.
    const result = buildConversationItems(
      [
        userPromptMsg(1, 1, "hi"),
        statusMsg(2, "compacting"),
        statusMsg(3, "compacting_failed", undefined, "Not enough messages."),
      ],
      null,
    );

    const statusItems = result.items.filter(
      (i): i is Extract<ConversationItem, { type: "session_update" }> =>
        i.type === "session_update" && i.update.sessionUpdate === "status",
    );
    // Spinner row (now complete) + the failure row.
    expect(statusItems.map((i) => i.update)).toEqual([
      {
        sessionUpdate: "status",
        status: "compacting",
        isComplete: true,
        startedAt: 2,
      },
      {
        sessionUpdate: "status",
        status: "compacting_failed",
        error: "Not enough messages.",
      },
    ]);
    expect(result.isCompacting).toBe(false);
  });

  it("renders a terminal refusal as a status row carrying the explanation", () => {
    const result = buildConversationItems(
      [
        userPromptMsg(1, 1, "hi"),
        refusalStatusMsg(2, "refusal", {
          explanation: "This request was declined.",
        }),
      ],
      null,
    );

    const statusItems = result.items.filter(
      (i): i is Extract<ConversationItem, { type: "session_update" }> =>
        i.type === "session_update" && i.update.sessionUpdate === "status",
    );
    expect(statusItems.map((i) => i.update)).toEqual([
      {
        sessionUpdate: "status",
        status: "refusal",
        explanation: "This request was declined.",
      },
    ]);
  });

  it("renders a refusal fallback status row carrying the model swap", () => {
    const result = buildConversationItems(
      [
        userPromptMsg(1, 1, "hi"),
        refusalStatusMsg(2, "refusal_fallback", {
          fromModel: "claude-fable-5",
          toModel: "claude-opus-4-8",
        }),
      ],
      null,
    );

    const statusItems = result.items.filter(
      (i): i is Extract<ConversationItem, { type: "session_update" }> =>
        i.type === "session_update" && i.update.sessionUpdate === "status",
    );
    expect(statusItems.map((i) => i.update)).toEqual([
      {
        sessionUpdate: "status",
        status: "refusal_fallback",
        fromModel: "claude-fable-5",
        toModel: "claude-opus-4-8",
      },
    ]);
  });

  it("marks cloud turns complete from structured turn completion notifications", () => {
    const result = buildConversationItems(
      [userPromptMsg(10, 42, "hello"), turnCompleteMsg(25)],
      null,
    );

    expect(result.lastTurnInfo).toEqual({
      isComplete: true,
      durationMs: 15,
      stopReason: "end_turn",
    });
  });

  it("keeps attachment-only prompts visible", () => {
    const uri = makeAttachmentUri("/tmp/test.txt");

    const events: AcpMessage[] = [
      {
        type: "acp_message",
        ts: 1,
        message: {
          jsonrpc: "2.0",
          id: 1,
          method: "session/prompt",
          params: {
            prompt: [
              {
                type: "resource",
                resource: {
                  uri,
                  text: "watup",
                  mimeType: "text/plain",
                },
              },
            ],
          },
        },
      },
    ];

    const result = buildConversationItems(events, null);

    expect(result.items).toEqual([
      {
        type: "user_message",
        id: "turn-1-1-user",
        content: "",
        timestamp: 1,
        attachments: [
          {
            id: uri,
            label: "test.txt",
          },
        ],
      },
    ]);
  });

  it("extracts cloud resource_link attachments into user messages", () => {
    const fileUri = "file:///tmp/workspace/attachments/Receipt-2264-0277.pdf";

    const events: AcpMessage[] = [
      {
        type: "acp_message",
        ts: 1,
        message: {
          jsonrpc: "2.0",
          id: 1,
          method: "session/prompt",
          params: {
            prompt: [
              { type: "text", text: "what is this about?" },
              {
                type: "resource_link",
                uri: fileUri,
                name: "Receipt-2264-0277.pdf",
              },
            ],
          },
        },
      },
    ];

    const result = buildConversationItems(events, null);

    expect(result.items).toEqual([
      {
        type: "user_message",
        id: "turn-1-1-user",
        content: "what is this about?",
        timestamp: 1,
        attachments: [
          {
            id: fileUri,
            label: "Receipt-2264-0277.pdf",
          },
        ],
      },
    ]);
  });

  describe("progress notifications", () => {
    it("aggregates progress events arriving before the first prompt into one progress_group item in arrival order", () => {
      const events: AcpMessage[] = [
        progressMsg(1, "sandbox", "in_progress", "Setting up sandbox"),
        progressMsg(2, "sandbox", "completed", "Set up sandbox"),
        progressMsg(3, "clone", "in_progress", "Cloning repository"),
        progressMsg(4, "clone", "completed", "Cloned repository"),
        progressMsg(5, "checkout", "in_progress", "Checking out branch main"),
      ];

      const result = buildConversationItems(events, null);

      const groups = findProgressGroups(result.items);
      expect(groups).toHaveLength(1);
      const update = groups[0];
      expect(update.steps.map((s) => [s.key, s.status, s.label])).toEqual([
        ["sandbox", "completed", "Set up sandbox"],
        ["clone", "completed", "Cloned repository"],
        ["checkout", "in_progress", "Checking out branch main"],
      ]);
      expect(update.isActive).toBe(true);
    });

    it("marks the progress group inactive once no step is in_progress", () => {
      const events: AcpMessage[] = [
        progressMsg(1, "sandbox", "completed", "Set up sandbox"),
        progressMsg(2, "clone", "completed", "Cloned repository"),
        progressMsg(3, "agent", "completed", "Started agent"),
      ];

      const result = buildConversationItems(events, null);
      const [group] = findProgressGroups(result.items);
      expect(group.isActive).toBe(false);
    });

    it("keeps the agent step in_progress until its run emits run_started", () => {
      const runStarted = (ts: number, runId: string): AcpMessage => ({
        type: "acp_message",
        ts,
        message: {
          jsonrpc: "2.0",
          method: "_posthog/run_started",
          params: { runId },
        },
      });
      const base: AcpMessage[] = [
        progressMsg(
          1,
          "sandbox",
          "completed",
          "Restored sandbox",
          undefined,
          "setup:run-9",
        ),
        progressMsg(
          2,
          "agent",
          "completed",
          "Started agent",
          undefined,
          "setup:run-9",
        ),
      ];

      const gated = findProgressGroups(
        buildConversationItems(base, null).items,
      )[0];
      expect(gated.steps.find((s) => s.key === "agent")?.status).toBe(
        "in_progress",
      );
      expect(gated.isActive).toBe(true);

      const ready = findProgressGroups(
        buildConversationItems([...base, runStarted(3, "run-9")], null).items,
      )[0];
      expect(ready.steps.find((s) => s.key === "agent")?.status).toBe(
        "completed",
      );
      expect(ready.isActive).toBe(false);
    });

    it("opens a separate progress_group per group id — distinct groups coexist inline", () => {
      const events: AcpMessage[] = [
        // Pre-prompt setup group.
        progressMsg(
          1,
          "sandbox",
          "in_progress",
          "Setting up sandbox",
          undefined,
          "setup",
        ),
        progressMsg(
          2,
          "sandbox",
          "completed",
          "Set up sandbox",
          undefined,
          "setup",
        ),
        // First user prompt + response.
        userPromptMsg(10, 1, "hi"),
        promptResponseMsg(20, 1),
        // A distinct group id — must open its own card, not join "setup".
        progressMsg(
          30,
          "push",
          "in_progress",
          "Creating pull request",
          undefined,
          "pr_create",
        ),
        progressMsg(
          40,
          "push",
          "completed",
          "Created pull request",
          undefined,
          "pr_create",
        ),
      ];

      const result = buildConversationItems(events, null);
      const groups = findProgressGroups(result.items);
      expect(groups).toHaveLength(2);

      expect(groups[0].steps.map((s) => s.key)).toEqual(["sandbox"]);
      expect(groups[0].isActive).toBe(false);

      expect(groups[1].steps.map((s) => [s.key, s.status, s.label])).toEqual([
        ["push", "completed", "Created pull request"],
      ]);
      expect(groups[1].isActive).toBe(false);
    });

    it("late completion events update the original group regardless of turn boundaries", () => {
      const events: AcpMessage[] = [
        // `sandbox` starts in the pre-prompt implicit turn.
        progressMsg(
          1,
          "sandbox",
          "in_progress",
          "Setting up sandbox",
          undefined,
          "setup",
        ),
        // User prompt + response come in before the completion lands.
        userPromptMsg(10, 1, "hi"),
        promptResponseMsg(20, 1),
        // The completion arrives late, after the turn boundary — it should
        // still update the existing "setup" card, not open a new one.
        progressMsg(
          30,
          "sandbox",
          "completed",
          "Set up sandbox",
          undefined,
          "setup",
        ),
      ];

      const result = buildConversationItems(events, null);
      const groups = findProgressGroups(result.items);
      expect(groups).toHaveLength(1);
      expect(groups[0].steps).toEqual([
        {
          key: "sandbox",
          status: "completed",
          label: "Set up sandbox",
          detail: undefined,
        },
      ]);
      expect(groups[0].isActive).toBe(false);
    });

    it("drops progress events missing a group id", () => {
      const events: AcpMessage[] = [
        {
          type: "acp_message",
          ts: 1,
          message: {
            jsonrpc: "2.0",
            method: "_posthog/progress",
            params: {
              step: "sandbox",
              status: "in_progress",
              label: "Setting up sandbox",
            },
          },
        },
      ];

      const result = buildConversationItems(events, null);
      expect(findProgressGroups(result.items)).toHaveLength(0);
    });

    it("replaces the step entry when a later event revisits the same key with a new label/status", () => {
      const events: AcpMessage[] = [
        progressMsg(1, "sandbox", "in_progress", "Setting up sandbox"),
        progressMsg(2, "sandbox", "failed", "Set up failed", "timeout"),
      ];

      const result = buildConversationItems(events, null);
      const [group] = findProgressGroups(result.items);
      expect(group.steps).toHaveLength(1);
      expect(group.steps[0]).toEqual({
        key: "sandbox",
        status: "failed",
        label: "Set up failed",
        detail: "timeout",
      });
    });

    it("hides debug-level console logs by default and renders them inline when showDebugLogs is true", () => {
      const events: AcpMessage[] = [
        progressMsg(1, "sandbox", "in_progress", "Setting up sandbox"),
        consoleMsg(2, "sandbox provisioned", "debug"),
      ];

      const hidden = buildConversationItems(events, null);
      expect(
        hidden.items.some(
          (i) =>
            i.type === "session_update" && i.update.sessionUpdate === "console",
        ),
      ).toBe(false);

      const shown = buildConversationItems(events, null, {
        showDebugLogs: true,
      });
      expect(
        shown.items.some(
          (i) =>
            i.type === "session_update" && i.update.sessionUpdate === "console",
        ),
      ).toBe(true);
    });

    it("emits no progress group for a conversation without progress notifications", () => {
      const events: AcpMessage[] = [userPromptMsg(1, 1, "hi")];

      const result = buildConversationItems(events, null);
      expect(findProgressGroups(result.items)).toHaveLength(0);
    });
  });

  describe("resources_used", () => {
    it("does not render an inline item (surfaced in the persistent bar)", () => {
      const events: AcpMessage[] = [
        userPromptMsg(1, 1, "list my experiments"),
        agentMessageMsg(2, "Here are your experiments."),
        resourcesUsedMsg(3, [{ id: "experiments", label: "Experiments" }]),
        promptResponseMsg(4, 1),
      ];

      const result = buildConversationItems(events, false);

      // The notification must not produce any conversation item — it's now
      // handled out-of-band by SessionResourcesBar / accumulateSessionResources.
      expect(
        result.items.some(
          (i) =>
            i.type === "session_update" &&
            // biome-ignore lint/suspicious/noExplicitAny: removed union member
            (i.update.sessionUpdate as any) === "resources_used",
        ),
      ).toBe(false);
    });
  });

  describe("completedToolCallCount", () => {
    const toolCallMsg = (
      ts: number,
      toolCallId: string,
      extra: Record<string, unknown> = {},
    ): AcpMessage => ({
      type: "acp_message",
      ts,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call",
            toolCallId,
            kind: "execute",
            status: "pending",
            title: toolCallId,
            ...extra,
          },
        },
      },
    });

    const toolUpdateMsg = (
      ts: number,
      toolCallId: string,
      extra: Record<string, unknown>,
    ): AcpMessage => ({
      type: "acp_message",
      ts,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: { sessionUpdate: "tool_call_update", toolCallId, ...extra },
        },
      },
    });

    it("starts at zero with no tool calls", () => {
      const result = buildConversationItems([userPromptMsg(1, 1, "hi")], null);
      expect(result.completedToolCallCount).toBe(0);
    });

    it("stays at zero while a tool call is still pending", () => {
      const events = [userPromptMsg(1, 1, "go"), toolCallMsg(2, "t1")];
      expect(buildConversationItems(events, true).completedToolCallCount).toBe(
        0,
      );
    });

    it.each(["completed", "failed", "cancelled"])(
      "counts a tool call once it settles to %s",
      (status) => {
        const events = [
          userPromptMsg(1, 1, "go"),
          toolCallMsg(2, "t1"),
          toolUpdateMsg(3, "t1", { status }),
        ];
        expect(
          buildConversationItems(events, true).completedToolCallCount,
        ).toBe(1);
      },
    );

    it("does not double-count repeated updates after settling", () => {
      const events = [
        userPromptMsg(1, 1, "go"),
        toolCallMsg(2, "t1"),
        toolUpdateMsg(3, "t1", { status: "completed" }),
        toolUpdateMsg(4, "t1", {
          status: "completed",
          content: [{ type: "content", content: { type: "text", text: "x" } }],
        }),
      ];
      expect(buildConversationItems(events, true).completedToolCallCount).toBe(
        1,
      );
    });

    it("accumulates across multiple completed tool calls and turns", () => {
      const events = [
        userPromptMsg(1, 1, "go"),
        toolCallMsg(2, "t1"),
        toolUpdateMsg(3, "t1", { status: "completed" }),
        toolCallMsg(4, "t2"),
        toolUpdateMsg(5, "t2", { status: "completed" }),
        promptResponseMsg(6, 1),
        userPromptMsg(7, 2, "again"),
        toolCallMsg(8, "t3"),
        toolUpdateMsg(9, "t3", { status: "completed" }),
      ];
      expect(buildConversationItems(events, true).completedToolCallCount).toBe(
        3,
      );
    });
  });

  describe("session_update timestamps", () => {
    const toolCallMsg = (ts: number, toolCallId: string): AcpMessage => ({
      type: "acp_message",
      ts,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call",
            toolCallId,
            kind: "execute",
            status: "pending",
            title: toolCallId,
          },
        },
      },
    });

    const firstSessionUpdate = (items: ConversationItem[]) =>
      items.find((i) => i.type === "session_update") as
        | Extract<ConversationItem, { type: "session_update" }>
        | undefined;

    it("stamps an agent message with the first chunk's ts and keeps it across merges", () => {
      const events = [
        userPromptMsg(1, 1, "hi"),
        agentMessageMsg(5, "Hello"),
        agentMessageMsg(9, " there"),
      ];
      const item = firstSessionUpdate(
        buildConversationItems(events, true).items,
      );
      expect(item?.update.sessionUpdate).toBe("agent_message_chunk");
      expect(item?.timestamp).toBe(5);
    });

    it("stamps a tool call with its ts", () => {
      const events = [userPromptMsg(1, 1, "go"), toolCallMsg(4, "t1")];
      const item = firstSessionUpdate(
        buildConversationItems(events, true).items,
      );
      expect(item?.update.sessionUpdate).toBe("tool_call");
      expect(item?.timestamp).toBe(4);
    });
  });

  describe("turn boundaries after completion", () => {
    function isTextChunk(item: ConversationItem): item is Extract<
      ConversationItem,
      { type: "session_update" }
    > & {
      update: {
        sessionUpdate: "agent_message_chunk";
        content: { type: "text"; text: string };
      };
    } {
      return (
        item.type === "session_update" &&
        item.update.sessionUpdate === "agent_message_chunk" &&
        item.update.content.type === "text"
      );
    }

    it("does not merge untracked content into an already-completed turn", () => {
      // Mirrors a scheduled wakeup: it resumes the session outside of
      // session/prompt, so this chunk arrives with no queued turn behind it.
      const events = [
        userPromptMsg(1, 1, "hi"),
        agentMessageMsg(2, "you'll get a ping shortly."),
        turnCompleteMsg(3),
        agentMessageMsg(4, "ping"),
      ];

      const items = buildConversationItems(events, true).items;
      const chunks = items.filter(isTextChunk);

      expect(chunks.map((c) => c.update.content.text)).toEqual([
        "you'll get a ping shortly.",
        "ping",
      ]);
      expect(chunks[0].turnContext).not.toBe(chunks[1].turnContext);
    });

    it("still merges consecutive chunks within the same open turn", () => {
      const events = [
        userPromptMsg(1, 1, "hi"),
        agentMessageMsg(2, "Hello"),
        agentMessageMsg(3, " there"),
      ];

      const items = buildConversationItems(events, true).items;
      const chunks = items.filter(isTextChunk);

      expect(chunks.map((c) => c.update.content.text)).toEqual(["Hello there"]);
    });

    it("separates consecutive background replies with no queued turn behind either", () => {
      // Mirrors a Monitor tool streaming several background events in a
      // row: each reply resumes the session outside of session/prompt, so
      // none of them ever gets a real user turn in between to reset on.
      const events = [
        userPromptMsg(1, 1, "use a monitor"),
        agentMessageMsg(2, "Monitor is running."),
        turnCompleteMsg(3),
        agentMessageMsg(10, "ping 1 received."),
        backgroundTurnCompleteMsg(11),
        agentMessageMsg(20, "ping 2 received."),
        backgroundTurnCompleteMsg(21),
        agentMessageMsg(30, "ping 3 received."),
        backgroundTurnCompleteMsg(31),
      ];

      const items = buildConversationItems(events, true).items;
      const chunks = items.filter(isTextChunk);

      expect(chunks.map((c) => c.update.content.text)).toEqual([
        "Monitor is running.",
        "ping 1 received.",
        "ping 2 received.",
        "ping 3 received.",
      ]);
      const distinctContexts = new Set(chunks.map((c) => c.turnContext));
      expect(distinctContexts.size).toBe(4);
    });

    it("computes a real duration for an implicit turn once a background reply completes it", () => {
      const events = [
        userPromptMsg(1, 1, "use a monitor"),
        agentMessageMsg(2, "Monitor is running."),
        turnCompleteMsg(3),
        agentMessageMsg(10, "ping 1 received."),
        backgroundTurnCompleteMsg(35),
      ];

      const { lastTurnInfo } = buildConversationItems(events, true);

      expect(lastTurnInfo?.isComplete).toBe(true);
      expect(lastTurnInfo?.durationMs).toBeGreaterThan(0);
    });

    it("does not spawn a phantom turn for a silent trailing update like usage_update", () => {
      // A usage_update (or any other content-less session/update) commonly
      // trails the final background reply. It must not reopen a turn on its
      // own and clobber the real reply's duration.
      const events = [
        userPromptMsg(1, 1, "use a monitor"),
        agentMessageMsg(2, "Monitor is running."),
        turnCompleteMsg(3),
        agentMessageMsg(10, "ping 1 received."),
        backgroundTurnCompleteMsg(35),
        usageUpdateMsg(50),
      ];

      const { lastTurnInfo } = buildConversationItems(events, true);

      expect(lastTurnInfo?.isComplete).toBe(true);
      expect(lastTurnInfo?.durationMs).toBeGreaterThan(0);
    });
  });
});

// Local alias kept intentionally narrow to the shape we care about in tests.
type RenderItemUnion = Extract<
  ConversationItem,
  { type: "session_update" }
>["update"];

type ProgressGroupUpdate = Extract<
  RenderItemUnion,
  { sessionUpdate: "progress_group" }
>;

function findProgressGroups(items: ConversationItem[]): ProgressGroupUpdate[] {
  const groups: ProgressGroupUpdate[] = [];
  for (const item of items) {
    if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "progress_group"
    ) {
      groups.push(item.update);
    }
  }
  return groups;
}
