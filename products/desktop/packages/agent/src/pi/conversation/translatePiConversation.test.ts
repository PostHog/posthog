import type { AssistantMessage } from "@earendil-works/pi-ai";
import { describe, expect, it } from "vitest";
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

    const streamed = translator.translateEvent({
      type: "message_update",
      message,
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "complete",
        partial: message,
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

  it("does not repeat streamed content when assistant timestamps collide", () => {
    const translator = createPiConversationTranslator();
    const first = assistant([{ type: "text", text: "first" }]);
    const second = assistant([{ type: "text", text: "second" }]);

    translator.translateEvent({
      type: "message_update",
      message: first,
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "first",
        partial: first,
      },
    });
    translator.translateEvent({ type: "message_end", message: first });
    translator.translateEvent({
      type: "message_update",
      message: second,
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "second",
        partial: second,
      },
    });

    expect(
      translator.translateEvent({ type: "message_end", message: second }),
    ).toEqual([]);
  });

  it("completes a turn using the latest runtime timestamp", () => {
    const translator = createPiConversationTranslator();
    const laterMessage = assistant(
      [{ type: "text", text: "later" }],
      "stop",
      20,
    );
    const earlierMessage = assistant(
      [{ type: "text", text: "earlier" }],
      "stop",
      10,
    );

    translator.translateEvent({ type: "message_end", message: laterMessage });
    translator.translateEvent({ type: "message_end", message: earlierMessage });

    expect(translator.translateEvent({ type: "agent_settled" })).toEqual([
      { type: "turn_completed", timestamp: 20 },
    ]);
  });

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
    expect(
      translator.translateEvent({
        type: "auto_retry_end",
        success: true,
        attempt: 1,
      }),
    ).toEqual([
      {
        type: "runtime_status",
        timestamp: 10,
        status: "retrying",
        isComplete: true,
      },
    ]);
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
        },
      },
      {
        type: "tool_call_updated",
        timestamp: 20,
        toolCall: {
          id: "pi-bash-20",
          status: "completed",
          rawOutput: "/tmp/project",
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

    translator.translateEvent({
      type: "message_update",
      message,
      assistantMessageEvent: {
        type: "text_delta",
        contentIndex: 0,
        delta: "running",
        partial: message,
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
