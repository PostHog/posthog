import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
  ExtensionAPI,
  SessionManager,
  TurnEndEvent,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import type { PostHogAPIClient } from "../posthog-api";
import { PiContextSelection } from "./context-selection";
import { POSTHOG_PI_QUEUE_ENTRY_TYPE } from "./queue-persistence";

const user = (text: string, timestamp = 1): AgentMessage => ({
  role: "user",
  content: [{ type: "text", text }],
  timestamp,
});

const assistant = (
  stopReason: "stop" | "error" | "aborted",
): TurnEndEvent["message"] => ({
  role: "assistant",
  api: "openai-responses",
  provider: "posthog",
  model: "test",
  content: [{ type: "text", text: "answer" }],
  stopReason,
  timestamp: 2,
  usage: {
    input: 10,
    output: 2,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 12,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  },
});

function fixture(entries: ReturnType<SessionManager["getEntries"]> = []) {
  const api = {
    prepareContextSelection: vi.fn().mockResolvedValue({
      selection_id: "s",
      context: "Useful definition",
      mode: "treatment",
      reason: "selected",
    }),
    recordContextSelectionReceipt: vi.fn().mockResolvedValue(undefined),
  };
  const sessions = { getEntries: () => entries, appendCustomEntry: vi.fn() };
  const handlers = new Map<string, (event: never, ctx?: unknown) => unknown>();
  const selector = new PiContextSelection(
    {
      apiUrl: "https://example.test",
      apiKey: "test",
      projectId: 1,
      runId: "run",
      runtimeVersion: "v1",
    },
    sessions,
    api as unknown as PostHogAPIClient,
  );
  selector.extension.factory({
    on: (name: string, handler: (event: never, ctx?: unknown) => unknown) =>
      handlers.set(name, handler),
  } as unknown as ExtensionAPI);
  const context = async (
    messages: AgentMessage[],
    getSystemPrompt = () => "native system prompt",
  ) =>
    (await handlers.get("context")?.({ type: "context", messages } as never, {
      getSystemPrompt,
      model: { id: "test", provider: "posthog" },
    })) as { messages?: AgentMessage[] } | undefined;
  const start = async (turnIndex: number) =>
    handlers.get("turn_start")?.({
      type: "turn_start",
      turnIndex,
      timestamp: 1,
    } as never);
  const end = async (message: TurnEndEvent["message"], turnIndex = 0) =>
    handlers.get("turn_end")?.({
      type: "turn_end",
      turnIndex,
      message,
      toolResults: [],
    } as never);
  return { selector, api, sessions, context, start, end };
}

describe("Pi context selection", () => {
  it.each(["stop", "error", "aborted"] as const)(
    "archives native context and the model outcome (%s)",
    async (stopReason) => {
      const { selector, api, context, end } = fixture();
      selector.register("human-1", "activation");
      expect(api.prepareContextSelection).not.toHaveBeenCalled();
      const messages = [user("activation")];
      const result = await context(messages);
      expect(result?.messages).toHaveLength(2);
      expect(messages).toHaveLength(1);
      expect(result?.messages?.[1]).toMatchObject({
        role: "custom",
        display: false,
        content: "Useful definition",
      });
      expect(api.prepareContextSelection).toHaveBeenCalledWith(
        expect.objectContaining({
          message_id: "human-1",
          history_source: "runtime",
        }),
      );
      expect(api.recordContextSelectionReceipt).toHaveBeenCalledTimes(1);
      expect(api.recordContextSelectionReceipt).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "dispatching",
          prompt: {
            format: "pi_context",
            messages: result?.messages,
            system_prompt: "native system prompt",
            model: { id: "test", provider: "posthog" },
          },
        }),
      );
      await end(assistant(stopReason));
      expect(api.recordContextSelectionReceipt.mock.calls[1][0]).toMatchObject({
        status: stopReason === "stop" ? "completed" : "failed",
        trace_id: "",
        usage: { scope: "pi_model_turn", totalTokens: 12 },
      });
      await context(messages);
      expect(api.prepareContextSelection).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["unregistered", "steer", "slash", "cleared", "rejected"])(
    "does not select for %s inputs",
    async (kind) => {
      const { selector, api, context } = fixture();
      const text = kind === "slash" ? "/compact" : "activation";
      if (kind !== "unregistered" && kind !== "steer")
        selector.register("human-1", text);
      if (kind === "cleared") selector.clearPending();
      if (kind === "rejected") selector.unregister("human-1");
      await context([user(text)]);
      expect(api.prepareContextSelection).not.toHaveBeenCalled();
    },
  );

  it("skips identical messages that are both waiting", async () => {
    const { selector, api, context } = fixture();
    selector.register("human-1", "activation");
    selector.register("human-2", "activation");
    await context([user("activation", 1)]);
    await context([user("activation", 1), user("activation", 2)]);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
  });

  it("skips restored queued messages that have no reliable request ID", async () => {
    const { selector, api, context } = fixture([
      {
        type: "custom",
        customType: POSTHOG_PI_QUEUE_ENTRY_TYPE,
        id: "entry",
        parentId: null,
        timestamp: "2026-01-01T00:00:00Z",
        data: { steering: [], followUp: ["activation"] },
      },
    ]);
    selector.register("human-2", "activation");
    await context([user("activation")]);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
  });

  it("does not reuse a cancelled request ID for later identical text", async () => {
    const { selector, api, context } = fixture();
    selector.register("human-1", "activation");
    selector.unregister("human-1");
    selector.register("human-2", "activation");
    await context([user("activation")]);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
  });

  it("does not assign a queued request ID to a steer with the same text", async () => {
    const { selector, api, context } = fixture();
    selector.register("queued", "activation");
    selector.blockText("activation");
    await context([user("activation")]);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
  });

  it("does not consume another request ID after preparation throws", async () => {
    const { selector, api, context } = fixture();
    selector.register("human-1", "activation");
    await context([user("activation", 1)], () => {
      throw new Error("system prompt unavailable");
    });
    selector.register("human-2", "activation");
    await context([user("activation", 1)]);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
    await context([user("activation", 1), user("activation", 2)]);
    expect(api.prepareContextSelection).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "human-2" }),
    );
  });

  it("finishes the earlier delivery when another message starts", async () => {
    const { selector, api, context, start, end } = fixture();
    await start(0);
    selector.register("human-1", "first");
    await context([user("first", 1)]);
    await start(1);
    selector.register("human-2", "second");
    await context([user("first", 1), user("second", 2)]);
    expect(api.recordContextSelectionReceipt).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "failed",
        stop_reason: "superseded",
      }),
    );
    await end(assistant("stop"), 0);
    expect(api.recordContextSelectionReceipt).toHaveBeenCalledTimes(3);
    await end(assistant("stop"), 1);
    expect(api.recordContextSelectionReceipt).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "completed" }),
    );
  });

  it.each(["prepare", "receipt"])(
    "does not inject when %s fails",
    async (stage) => {
      const { selector, api, context } = fixture();
      if (stage === "prepare")
        api.prepareContextSelection.mockRejectedValue(new Error("offline"));
      else
        api.recordContextSelectionReceipt.mockRejectedValue(
          new Error("offline"),
        );
      selector.register("human-1", "activation");
      const messages = [user("activation")];
      expect((await context(messages))?.messages).toEqual(messages);
    },
  );
});
