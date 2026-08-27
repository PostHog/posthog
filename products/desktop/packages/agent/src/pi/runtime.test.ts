import type { AssistantMessage, UserMessage } from "@earendil-works/pi-ai";
import { describe, expect, it, vi } from "vitest";
import type { PiRpcClient, PiRpcEvent } from "./rpc-client";
import { PiRuntime } from "./runtime";

function assistant(text: string): AssistantMessage {
  return {
    role: "assistant",
    content: [{ type: "text", text }],
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
    stopReason: "stop",
    timestamp: 1,
  };
}

function createClient() {
  let listener: (event: PiRpcEvent) => void = () => {};
  const send = vi.fn();
  const client = {
    onEvent: vi.fn((nextListener) => {
      listener = nextListener;
      return () => {};
    }),
    send,
    getQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    clearQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
  } as unknown as PiRpcClient;

  return {
    client,
    emit: (event: PiRpcEvent) => listener(event),
    send,
  };
}

describe("PiRuntime", () => {
  it("streams and completes direct bash from one RPC operation", async () => {
    const { client, emit, send } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);
    send.mockImplementation(async () => {
      emit({ type: "bash_execution_update", id: "req_1", delta: "one\n" });
      emit({ type: "bash_execution_update", id: "req_1", delta: "two\n" });
      return {
        type: "response",
        command: "bash",
        success: true,
        data: {
          output: "one\ntwo\n",
          exitCode: 0,
          cancelled: false,
          truncated: false,
        },
      };
    });

    await runtime.sendCommand({ type: "bash", command: "print-lines" });

    const events = conversationListener.mock.calls.map(([event]) => event);
    expect(events).toHaveLength(4);
    expect(events[0]).toMatchObject({
      type: "tool_call_started",
      toolCall: { title: "print-lines", status: "in_progress" },
    });
    const toolCallId = events[0].toolCall.id;
    expect(events[2]).toMatchObject({
      type: "tool_call_updated",
      toolCall: {
        id: toolCallId,
        content: [
          {
            type: "content",
            content: { type: "text", text: "one\ntwo\n" },
          },
        ],
      },
    });
    expect(events[3]).toMatchObject({
      type: "tool_call_updated",
      toolCall: { id: toolCallId, status: "completed" },
    });
  });

  it("uses the native command id for the echoed user message", async () => {
    const { client, emit, send } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);
    const message: UserMessage = {
      role: "user",
      content: "hello",
      timestamp: 1,
    };
    send.mockImplementation(async () => {
      emit({ type: "message_end", message });
      return {
        id: "message-1",
        type: "response",
        command: "prompt",
        success: true,
      };
    });

    await runtime.sendCommand({
      id: "message-1",
      type: "prompt",
      message: "hello",
    });

    expect(conversationListener).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "user_message",
        id: "message-1",
      }),
    );
  });

  it("does not apply an extension command id to a later user message", async () => {
    const { client, emit, send } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);
    send.mockImplementation(async (command: { message?: string }) => {
      if (command.message === "next") {
        emit({
          type: "message_end",
          message: { role: "user", content: "next", timestamp: 1 },
        });
      }
      return {
        type: "response",
        command: "prompt",
        success: true,
      };
    });

    await runtime.sendCommand({
      id: "extension-id",
      type: "prompt",
      message: "/extension",
    });
    await runtime.sendCommand({
      id: "message-id",
      type: "prompt",
      message: "next",
    });

    expect(conversationListener).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "user_message",
        id: "message-id",
      }),
    );
  });

  it("drops cleared queued message ids before matching later messages", async () => {
    const { client, emit, send } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);
    send.mockResolvedValue({
      type: "response",
      command: "steer",
      success: true,
    });

    await runtime.sendCommand({
      id: "cleared-id",
      type: "steer",
      message: "continue",
    });
    runtime.clearPendingQueuedUserMessages();
    send.mockImplementationOnce(async () => {
      emit({
        type: "message_end",
        message: { role: "user", content: "continue", timestamp: 1 },
      });
      return { type: "response", command: "prompt", success: true };
    });
    await runtime.sendCommand({
      id: "current-id",
      type: "prompt",
      message: "continue",
    });

    expect(conversationListener).toHaveBeenCalledWith(
      expect.objectContaining({ type: "user_message", id: "current-id" }),
    );
  });

  it("rejects concurrent direct bash commands", async () => {
    const { client, send } = createClient();
    const runtime = new PiRuntime(client);
    let resolveBash: (value: unknown) => void = () => {};
    send.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveBash = resolve;
        }),
    );

    const first = runtime.sendCommand({ type: "bash", command: "sleep 1" });
    await expect(
      runtime.sendCommand({ type: "bash", command: "pwd" }),
    ).rejects.toThrow("already running");
    resolveBash({
      type: "response",
      command: "bash",
      success: true,
      data: { output: "", exitCode: 0, cancelled: false },
    });
    await first;
  });

  it("forwards native queue snapshots", () => {
    const { client, emit } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);

    emit({
      type: "queue_update",
      steering: ["fix this"],
      followUp: ["then summarize"],
    });

    expect(conversationListener).toHaveBeenCalledWith({
      type: "queue_update",
      timestamp: expect.any(Number),
      steering: ["fix this"],
      followUp: ["then summarize"],
    });
  });

  it("routes extension UI and errors outside the conversation stream", () => {
    const { client, emit } = createClient();
    const runtime = new PiRuntime(client);
    const extensionListener = vi.fn();
    const conversationListener = vi.fn();
    runtime.onExtensionEvent(extensionListener);
    runtime.onConversationEvent(conversationListener);

    emit({
      type: "extension_ui_request",
      id: "extension-1",
      method: "notify",
      message: "Done",
    });
    emit({
      type: "extension_error",
      extensionPath: "/extensions/example.ts",
      event: "tool_call",
      error: "boom",
    });

    expect(extensionListener).toHaveBeenCalledTimes(2);
    expect(conversationListener).not.toHaveBeenCalled();
  });

  it("normalizes live Pi events before forwarding them", () => {
    const { client, emit } = createClient();
    const runtime = new PiRuntime(client);
    const conversationListener = vi.fn();
    runtime.onConversationEvent(conversationListener);

    emit({ type: "message_end", message: assistant("hello") });

    expect(conversationListener).toHaveBeenCalledWith({
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "hello" },
    });
  });
});
