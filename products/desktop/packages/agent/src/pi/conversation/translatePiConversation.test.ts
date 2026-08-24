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
});
