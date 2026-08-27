import type { AssistantMessage } from "@earendil-works/pi-ai";
import { describe, expect, it, vi } from "vitest";
import { createPiConversationTranslator } from "./translatePiConversation";

function assistant(
  content: AssistantMessage["content"],
  stopReason: AssistantMessage["stopReason"] = "stop",
  timestamp = 10,
): AssistantMessage {
  return {
    role: "assistant",
    content,
    api: "anthropic-messages" as AssistantMessage["api"],
    provider: "anthropic" as AssistantMessage["provider"],
    model: "test-model",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason,
    timestamp,
  };
}

describe("createPiConversationTranslator", () => {
  it("keeps complete assistant content when translating history", () => {
    const translator = createPiConversationTranslator();

    expect(
      translator.translateHistoryMessage(
        assistant([{ type: "text", text: "complete" }]),
      ),
    ).toContainEqual({
      type: "assistant_message_chunk",
      timestamp: 10,
      content: { type: "text", text: "complete" },
    });
  });

  it("uses message_update deltas without repeating cumulative text at message_end", () => {
    const translator = createPiConversationTranslator();
    const message = assistant([{ type: "text", text: "complete" }]);

    translator.translateEvent({ type: "message_start", message });
    const streamed = translator.translateEvent({
      type: "message_update",
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "complete",
      },
    });
    const ended = translator.translateEvent({ type: "message_end", message });

    expect(streamed).toEqual([
      {
        type: "assistant_message_chunk",
        timestamp: 10,
        content: { type: "text", text: "complete" },
      },
    ]);
    expect(ended).toEqual([]);
  });

  it("records assistant token usage on the completed turn", () => {
    vi.useFakeTimers();
    vi.setSystemTime(20);
    const translator = createPiConversationTranslator();
    const first = assistant([{ type: "text", text: "first" }]);
    first.usage.totalTokens = 1_200;
    const second = assistant([{ type: "text", text: "second" }]);
    second.usage.totalTokens = 900;

    translator.translateEvent({ type: "message_end", message: first });
    translator.translateEvent({ type: "message_end", message: second });

    expect(translator.translateEvent({ type: "agent_settled" })).toEqual([
      {
        type: "turn_completed",
        timestamp: 20,
        stopReason: "stop",
        totalTokens: 2_100,
      },
    ]);
    vi.useRealTimers();
  });

  it("does not carry usage from a terminally failed turn into the next turn", () => {
    vi.useFakeTimers();
    vi.setSystemTime(20);
    const translator = createPiConversationTranslator();
    const failedTurnMessage = assistant([{ type: "text", text: "failed" }]);
    failedTurnMessage.usage.totalTokens = 500;
    const nextTurnMessage = assistant([{ type: "text", text: "next" }]);
    nextTurnMessage.usage.totalTokens = 900;

    translator.translateEvent({
      type: "message_end",
      message: failedTurnMessage,
    });
    translator.translateEvent({
      type: "agent_end",
      messages: [failedTurnMessage],
      willRetry: false,
    });
    translator.translateEvent({
      type: "message_end",
      message: nextTurnMessage,
    });

    expect(translator.translateEvent({ type: "agent_settled" })).toEqual([
      {
        type: "turn_completed",
        timestamp: 20,
        stopReason: "stop",
        totalTokens: 900,
      },
    ]);
    vi.useRealTimers();
  });

  it("appends content missing from the streamed deltas at message_end", () => {
    const translator = createPiConversationTranslator();
    const message = assistant([{ type: "text", text: "complete" }]);

    translator.translateEvent({ type: "message_start", message });
    translator.translateEvent({
      type: "message_update",
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "comp",
      },
    });

    expect(translator.translateEvent({ type: "message_end", message })).toEqual(
      [
        {
          type: "assistant_message_chunk",
          timestamp: 10,
          content: { type: "text", text: "lete" },
        },
      ],
    );
  });

  it("keeps unstreamed content when assistant timestamps collide", () => {
    const translator = createPiConversationTranslator();
    const first = assistant([{ type: "text", text: "first" }]);
    const second = assistant([{ type: "text", text: "second" }]);

    translator.translateEvent({ type: "message_start", message: first });
    translator.translateEvent({
      type: "message_update",
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "first",
      },
    });
    translator.translateEvent({ type: "message_end", message: first });
    translator.translateEvent({ type: "message_start", message: second });

    expect(
      translator.translateEvent({ type: "message_end", message: second }),
    ).toEqual([
      {
        type: "assistant_message_chunk",
        timestamp: 10,
        content: { type: "text", text: "second" },
      },
    ]);
  });

  it("discards streamed state when the agent ends without message_end", () => {
    const translator = createPiConversationTranslator();
    const message = assistant([{ type: "text", text: "partial" }]);

    translator.translateEvent({ type: "message_start", message });
    translator.translateEvent({
      type: "agent_end",
      messages: [],
      willRetry: false,
    });

    expect(
      translator.translateEvent({
        type: "message_update",
        assistantMessageEvent: {
          type: "text_delta",
          contentIndex: 0,
          delta: "stale",
        },
      }),
    ).toEqual([]);
  });

  it.each(["stop", "aborted"] as const)(
    "completes a %s turn using the settlement time and final stop reason",
    (stopReason) => {
      vi.useFakeTimers();
      vi.setSystemTime(30);
      const translator = createPiConversationTranslator();
      const laterMessage = assistant(
        [{ type: "text", text: "later" }],
        stopReason,
        20,
      );
      const earlierMessage = assistant(
        [{ type: "text", text: "earlier" }],
        "stop",
        10,
      );

      translator.translateEvent({
        type: "message_end",
        message: earlierMessage,
      });
      translator.translateEvent({ type: "message_end", message: laterMessage });

      expect(translator.translateEvent({ type: "agent_settled" })).toEqual([
        { type: "turn_completed", timestamp: 30, stopReason },
      ]);
      vi.useRealTimers();
    },
  );

  it("translates retry lifecycle without rendering transient runtime errors", () => {
    const translator = createPiConversationTranslator();
    const failedMessage = {
      ...assistant([], "error"),
      errorMessage: "Rate limited",
    };

    expect(
      translator.translateEvent({
        type: "message_end",
        message: failedMessage,
      }),
    ).toEqual([]);
    expect(
      translator.translateEvent({
        type: "agent_end",
        messages: [failedMessage],
        willRetry: true,
      }),
    ).toEqual([]);
    expect(
      translator.translateEvent({
        type: "auto_retry_start",
        attempt: 1,
        maxAttempts: 3,
        delayMs: 1000,
        errorMessage: "Rate limited",
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 10,
        status: "retrying",
        message: "Rate limited",
        attempt: 1,
        maxAttempts: 3,
        delayMs: 1000,
      },
    ]);
    const retriedMessage = assistant([{ type: "text", text: "Done" }]);
    translator.translateEvent({
      type: "message_start",
      message: retriedMessage,
    });
    expect(
      translator.translateEvent({
        type: "message_update",
        assistantMessageEvent: {
          type: "text_delta",
          contentIndex: 0,
          delta: "Done",
        },
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 10,
        status: "retrying",
        isComplete: true,
      },
      {
        type: "assistant_message_chunk",
        timestamp: 10,
        content: { type: "text", text: "Done" },
      },
    ]);
    expect(
      translator.translateEvent({
        type: "auto_retry_end",
        success: true,
        attempt: 1,
      }),
    ).toEqual([]);
  });

  it("renders terminal Pi runtime errors inline", () => {
    const translator = createPiConversationTranslator();
    const failedMessage = {
      ...assistant([], "error"),
      errorMessage: "Authentication failed",
    };

    translator.translateEvent({ type: "message_end", message: failedMessage });

    expect(
      translator.translateEvent({
        type: "agent_end",
        messages: [failedMessage],
        willRetry: false,
      }),
    ).toEqual([
      {
        type: "runtime_error",
        timestamp: 10,
        errorType: "pi_runtime",
        message: "Authentication failed",
      },
    ]);
  });

  it("translates compaction lifecycle into generic runtime statuses", () => {
    const translator = createPiConversationTranslator();
    translator.translateHistoryMessage(
      assistant([{ type: "text", text: "complete" }]),
    );

    expect(
      translator.translateEvent({
        type: "compaction_start",
        reason: "manual",
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 10,
        status: "compacting",
      },
    ]);

    expect(
      translator.translateEvent({
        type: "compaction_end",
        reason: "manual",
        result: undefined,
        aborted: false,
        willRetry: false,
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 10,
        status: "compacting",
        isComplete: true,
      },
    ]);
  });

  it("emits the completed compaction summary without reloading history", () => {
    const translator = createPiConversationTranslator();

    expect(
      translator.translateEvent({
        type: "compaction_end",
        reason: "manual",
        result: {
          summary: "Earlier work was compacted.",
          firstKeptEntryId: "entry-1",
          tokensBefore: 1000,
        },
        aborted: false,
        willRetry: false,
      }),
    ).toMatchObject([
      {
        type: "runtime_status",
        status: "compacting",
        isComplete: true,
      },
      {
        type: "assistant_message_chunk",
        content: { type: "text", text: "Earlier work was compacted." },
      },
    ]);
  });

  it("translates compaction failures with their error", () => {
    const translator = createPiConversationTranslator();

    expect(
      translator.translateEvent({
        type: "compaction_end",
        reason: "manual",
        result: undefined,
        aborted: false,
        willRetry: false,
        errorMessage: "Not enough messages",
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 0,
        status: "compacting_failed",
        error: "Not enough messages",
      },
    ]);
  });

  it("translates direct bash history into the generic execute tool UI", () => {
    const translator = createPiConversationTranslator();

    expect(
      translator.translateHistoryMessage({
        role: "bashExecution",
        command: "pwd",
        output: "/tmp/project",
        exitCode: 0,
        cancelled: false,
        truncated: false,
        timestamp: 20,
      }),
    ).toEqual([
      {
        type: "tool_call_started",
        timestamp: 20,
        toolCall: {
          id: "pi-bash-20",
          title: "pwd",
          kind: "execute",
          status: "in_progress",
          rawInput: { command: "pwd" },
          origin: "user_shell",
        },
      },
      {
        type: "tool_call_updated",
        timestamp: 20,
        toolCall: {
          id: "pi-bash-20",
          status: "completed",
          rawOutput: "/tmp/project",
          origin: "user_shell",
          content: [
            {
              type: "content",
              content: { type: "text", text: "/tmp/project" },
            },
          ],
        },
      },
    ]);
  });

  it("streams direct RPC bash output into one execute tool call", () => {
    const translator = createPiConversationTranslator();
    const [started] = translator.beginDirectBash("printf hello");
    expect(started).toMatchObject({
      type: "tool_call_started",
      toolCall: {
        title: "printf hello",
        status: "in_progress",
      },
    });
    if (started?.type !== "tool_call_started") {
      throw new Error("Expected a direct bash tool call");
    }
    const toolCallId = started.toolCall.id;

    expect(
      translator.translateEvent({
        type: "bash_execution_update",
        id: "req_1",
        delta: "hel",
      }),
    ).toMatchObject([
      {
        type: "tool_call_updated",
        toolCall: {
          id: toolCallId,
          content: [
            {
              type: "content",
              content: { type: "text", text: "hel" },
            },
          ],
        },
      },
    ]);

    expect(
      translator.translateEvent({
        type: "bash_execution_update",
        id: "req_1",
        delta: "lo",
      }),
    ).toMatchObject([
      {
        type: "tool_call_updated",
        toolCall: {
          id: toolCallId,
          content: [
            {
              type: "content",
              content: { type: "text", text: "hello" },
            },
          ],
        },
      },
    ]);

    expect(
      translator.completeDirectBash({
        output: "hello",
        exitCode: 0,
        cancelled: false,
      }),
    ).toMatchObject([
      {
        type: "tool_call_updated",
        toolCall: {
          id: toolCallId,
          status: "completed",
          rawOutput: "hello",
          content: [
            {
              type: "content",
              content: { type: "text", text: "hello" },
            },
          ],
        },
      },
    ]);
  });

  it("throttles direct bash output by encoded byte size", () => {
    const translator = createPiConversationTranslator();
    translator.beginDirectBash("unicode-output");

    expect(
      translator.translateEvent({
        type: "bash_execution_update",
        id: "req_1",
        delta: "🙂".repeat(1_024),
      }),
    ).toHaveLength(1);
    expect(
      translator.translateEvent({
        type: "bash_execution_update",
        id: "req_1",
        delta: "x",
      }),
    ).toEqual([]);
  });

  it("preserves streamed direct bash output when the command fails", () => {
    const translator = createPiConversationTranslator();
    const [started] = translator.beginDirectBash("failing-command");
    if (started?.type !== "tool_call_started") {
      throw new Error("Expected a direct bash tool call");
    }

    translator.translateEvent({
      type: "bash_execution_update",
      id: "req_1",
      delta: "partial output",
    });

    expect(translator.failDirectBash("transport failed")).toMatchObject([
      {
        type: "tool_call_updated",
        toolCall: {
          id: started.toolCall.id,
          status: "failed",
          rawOutput: "partial output\n\ntransport failed",
        },
      },
    ]);
  });

  it("streams tool execution start, output updates, and completion", () => {
    const translator = createPiConversationTranslator();
    const message = assistant(
      [
        {
          type: "toolCall",
          id: "tool-1",
          name: "bash",
          arguments: { command: "printf hello" },
        },
      ],
      "toolUse",
    );

    translator.translateEvent({ type: "message_end", message });

    expect(
      translator.translateEvent({
        type: "tool_execution_start",
        toolCallId: "tool-1",
        toolName: "bash",
        args: { command: "printf hello" },
      }),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: { id: "tool-1", status: "in_progress" },
      },
    ]);

    expect(
      translator.translateEvent({
        type: "tool_execution_update",
        toolCallId: "tool-1",
        toolName: "bash",
        args: { command: "printf hello" },
        partialResult: {
          content: [{ type: "text", text: "hel" }],
          details: undefined,
        },
      }),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: {
          id: "tool-1",
          status: "in_progress",
          rawOutput: [{ type: "text", text: "hel" }],
          content: [
            {
              type: "content",
              content: { type: "text", text: "hel" },
            },
          ],
        },
      },
    ]);

    expect(
      translator.translateEvent({
        type: "tool_execution_end",
        toolCallId: "tool-1",
        toolName: "bash",
        result: {
          content: [{ type: "text", text: "hello" }],
          details: undefined,
        },
        isError: false,
      }),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: {
          id: "tool-1",
          status: "completed",
          rawOutput: [{ type: "text", text: "hello" }],
          content: [
            {
              type: "content",
              content: { type: "text", text: "hello" },
            },
          ],
        },
      },
    ]);
  });

  it("preserves tool calls when filtering streamed assistant content", () => {
    const translator = createPiConversationTranslator();
    const message = assistant([
      { type: "text", text: "running" },
      {
        type: "toolCall",
        id: "tool-1",
        name: "bash",
        arguments: { command: "pwd" },
      },
    ]);

    translator.translateEvent({ type: "message_start", message });
    translator.translateEvent({
      type: "message_update",
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "running",
      },
    });

    expect(translator.translateEvent({ type: "message_end", message })).toEqual(
      [
        {
          type: "tool_call_started",
          timestamp: 10,
          toolCall: {
            id: "tool-1",
            title: "bash",
            kind: "execute",
            status: "pending",
            rawInput: { command: "pwd" },
          },
        },
      ],
    );
  });

  it.each([
    ["completed", "stop"],
    ["stopped", "aborted"],
    ["failed", "error"],
  ])(
    "ends the turn when an agent flow message reports %s",
    (status, stopReason) => {
      const translator = createPiConversationTranslator();

      const events = translator.translateEvent({
        type: "message_end",
        message: {
          role: "custom",
          customType: "posthog-agent-flow",
          content: "Flow finished.",
          display: true,
          details: { flowId: "flow-1", flowName: "Plan and build", status },
          timestamp: 10,
        },
      });

      expect(events).toEqual([
        {
          type: "assistant_message_chunk",
          timestamp: 10,
          content: { type: "text", text: "Flow finished." },
        },
        { type: "turn_completed", timestamp: 10, stopReason },
      ]);
    },
  );

  it("renders flow steps as tool-call cards and fails an interrupted step", () => {
    const translator = createPiConversationTranslator();
    const flowMessage = (
      content: string,
      details: Record<string, unknown>,
    ) => ({
      type: "message_end" as const,
      message: {
        role: "custom" as const,
        customType: "posthog-agent-flow",
        content,
        display: true,
        details: { flowId: "flow-1", flowName: "Plan and build", ...details },
        timestamp: 10,
      },
    });

    const started = translator.translateEvent(
      flowMessage("**Step 1 of 2: Plan** (Sol, high effort)", {
        status: "running",
        event: "step_started",
        stepIndex: 0,
        stepCount: 2,
        stepName: "Plan",
      }),
    );
    expect(started).toEqual([
      {
        type: "tool_call_started",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:0",
          title: "Step 1 of 2: Plan (Sol, high effort)",
          kind: "other",
          status: "in_progress",
        },
      },
    ]);

    const finished = translator.translateEvent(
      flowMessage("the plan handoff", {
        status: "running",
        event: "step_finished",
        stepIndex: 0,
        stepCount: 2,
        stepName: "Plan",
      }),
    );
    expect(finished).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:0",
          status: "completed",
          content: [
            {
              type: "content",
              content: { type: "text", text: "the plan handoff" },
            },
          ],
        },
      },
    ]);

    translator.translateEvent(
      flowMessage("**Step 2 of 2: Build**", {
        status: "running",
        event: "step_started",
        stepIndex: 1,
        stepCount: 2,
        stepName: "Build",
      }),
    );
    const failed = translator.translateEvent(
      flowMessage("**Plan and build** failed.", {
        status: "failed",
        event: "flow_failed",
        stepIndex: 1,
        stepCount: 2,
      }),
    );
    expect(failed).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: { id: "agent-flow:flow-1:1", status: "failed" },
      },
      {
        type: "assistant_message_chunk",
        timestamp: 10,
        content: { type: "text", text: "**Plan and build** failed." },
      },
      { type: "turn_completed", timestamp: 10, stopReason: "error" },
    ]);
  });

  it("streams a step's live work as nested tool calls and its latest line", () => {
    const translator = createPiConversationTranslator();
    const stream = (event: Record<string, unknown>) =>
      translator.translateEvent({
        type: "posthog_flow_step_event",
        flowId: "flow-1",
        stepIndex: 0,
        timestamp: 10,
        event,
      } as never);

    expect(
      stream({
        kind: "tool_start",
        toolCallId: "t1",
        toolName: "bash",
        title: "bash: npm test",
      }),
    ).toEqual([
      {
        type: "tool_call_started",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:0:t1",
          parentId: "agent-flow:flow-1:0",
          title: "bash: npm test",
          kind: "execute",
          status: "in_progress",
        },
      },
    ]);

    expect(
      stream({ kind: "tool_end", toolCallId: "t1", toolName: "bash" }),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: { id: "agent-flow:flow-1:0:t1", status: "completed" },
      },
    ]);

    stream({ kind: "assistant_text", text: "first thought" });
    expect(stream({ kind: "assistant_text", text: "second" })).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:0",
          content: [
            {
              type: "content",
              content: { type: "text", text: "second" },
            },
          ],
        },
      },
    ]);
  });

  it("gives file children native locations and diffs", () => {
    const translator = createPiConversationTranslator();
    const stream = (event: Record<string, unknown>) =>
      translator.translateEvent({
        type: "posthog_flow_step_event",
        flowId: "flow-1",
        stepIndex: 0,
        timestamp: 10,
        event,
      } as never);

    const read = stream({
      kind: "tool_start",
      toolCallId: "t1",
      toolName: "read",
      title: "read: src/App.jsx",
      path: "src/App.jsx",
    });
    expect(read[0]?.type).toBe("tool_call_started");
    expect((read[0] as { toolCall: { locations?: unknown } }).toolCall).toEqual(
      expect.objectContaining({ locations: [{ path: "src/App.jsx" }] }),
    );

    const edit = stream({
      kind: "tool_start",
      toolCallId: "t2",
      toolName: "edit",
      path: "src/App.jsx",
      diff: { path: "src/App.jsx", oldText: "a", newText: "b" },
    });
    expect((edit[0] as { toolCall: { content?: unknown } }).toolCall).toEqual(
      expect.objectContaining({
        content: [
          { type: "diff", path: "src/App.jsx", oldText: "a", newText: "b" },
        ],
      }),
    );

    const editEnd = stream({
      kind: "tool_end",
      toolCallId: "t2",
      toolName: "edit",
      outputPreview: "ok",
    });
    expect(
      (editEnd[0] as { toolCall: { content?: unknown } }).toolCall.content,
    ).toBeUndefined();
  });

  it("renders handoff reviews as question cards and reopens the step on revision", () => {
    const translator = createPiConversationTranslator();
    const flowMessage = (
      content: string,
      details: Record<string, unknown>,
    ) => ({
      type: "message_end" as const,
      message: {
        role: "custom" as const,
        customType: "posthog-agent-flow",
        content,
        display: true,
        details: { flowId: "flow-1", flowName: "Plan and build", ...details },
        timestamp: 10,
      },
    });

    expect(
      translator.translateEvent(
        flowMessage("Review the Plan handoff above.", {
          status: "running",
          event: "approval_requested",
          approvalId: "a1",
          stepIndex: 0,
          stepName: "Plan",
        }),
      ),
    ).toEqual([
      {
        type: "tool_call_started",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:approval:a1",
          title: "Review the Plan handoff",
          kind: "question",
          status: "in_progress",
          content: [
            {
              type: "content",
              content: { type: "text", text: "Review the Plan handoff above." },
            },
          ],
        },
      },
    ]);

    expect(
      translator.translateEvent(
        flowMessage("Plan handoff sent back for changes.", {
          status: "running",
          event: "approval_resolved",
          approvalId: "a1",
          approvalOutcome: "rejected",
          stepIndex: 0,
        }),
      ),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: {
          id: "agent-flow:flow-1:approval:a1",
          status: "failed",
          content: [
            {
              type: "content",
              content: {
                type: "text",
                text: "Plan handoff sent back for changes.",
              },
            },
          ],
        },
      },
    ]);

    expect(
      translator.translateEvent(
        flowMessage("**Plan** is revising the handoff.", {
          status: "running",
          event: "step_revising",
          stepIndex: 0,
          stepName: "Plan",
        }),
      ),
    ).toEqual([
      {
        type: "tool_call_updated",
        timestamp: 10,
        toolCall: { id: "agent-flow:flow-1:0", status: "in_progress" },
      },
    ]);
  });

  it("does not end the turn for a running agent flow message", () => {
    const translator = createPiConversationTranslator();

    const events = translator.translateEvent({
      type: "message_end",
      message: {
        role: "custom",
        customType: "posthog-agent-flow",
        content: "Step 1 of 2 started.",
        display: true,
        details: {
          flowId: "flow-1",
          flowName: "Plan and build",
          status: "running",
        },
        timestamp: 10,
      },
    });

    expect(events).toEqual([
      {
        type: "assistant_message_chunk",
        timestamp: 10,
        content: { type: "text", text: "Step 1 of 2 started." },
      },
    ]);
  });

  it("keeps the document a step first reported when it revises", () => {
    const translator = createPiConversationTranslator();
    const finished = (version: number) =>
      translator.translateEvent({
        type: "message_end" as const,
        message: {
          role: "custom" as const,
          customType: "posthog-agent-flow",
          content: "the plan",
          display: true,
          details: {
            flowId: "flow-1",
            flowName: "Plan and build",
            status: "running",
            event: "step_finished",
            stepIndex: 0,
            stepName: "Plan",
            handoff: {
              stepIndex: 0,
              stepName: "Plan",
              title: "Plan",
              artifactName: "plan-and-build-step-1-plan.md",
              version,
              markdown: `version ${version}`,
            },
          },
          timestamp: 10,
        },
      });

    const rawInput = (events: unknown): unknown =>
      (events as [{ toolCall: { rawInput?: unknown } }])[0].toolCall.rawInput;

    expect(rawInput(finished(1))).toMatchObject({ version: 1 });
    expect(rawInput(finished(2))).toBeUndefined();
  });

  it("closes a review the flow never answered with a canceled line", () => {
    const translator = createPiConversationTranslator();
    const flowEvent = (details: Record<string, unknown>) =>
      translator.translateEvent({
        type: "message_end" as const,
        message: {
          role: "custom" as const,
          customType: "posthog-agent-flow",
          content: "Review the Plan handoff.",
          display: true,
          details: { flowId: "flow-1", flowName: "Plan and build", ...details },
          timestamp: 10,
        },
      });

    flowEvent({
      status: "running",
      event: "approval_requested",
      approvalId: "a1",
      stepIndex: 0,
      stepName: "Plan",
    });

    expect(
      flowEvent({ status: "stopped", event: "flow_stopped", stepIndex: 0 }),
    ).toContainEqual({
      type: "tool_call_updated",
      timestamp: 10,
      toolCall: {
        id: "agent-flow:flow-1:approval:a1",
        status: "failed",
        content: [
          {
            type: "content",
            content: {
              type: "text",
              text: "Review canceled because the flow stopped.",
            },
          },
        ],
      },
    });
  });
});
