import { createInterface } from "node:readline";
import { PassThrough } from "node:stream";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
  ExtensionAPI,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import type { PostHogAPIClient } from "../posthog-api";
import {
  observeContextSelectionFallback,
  PiContextSelection,
} from "./context-selection";
import { POSTHOG_PI_QUEUE_ENTRY_TYPE } from "./queue-persistence";

const user = (text: string, timestamp = 1): AgentMessage => ({
  role: "user",
  content: [{ type: "text", text }],
  timestamp,
});

function fixture(entries: ReturnType<SessionManager["getEntries"]> = []) {
  const api = {
    prepareContextSelection: vi.fn().mockResolvedValue({
      selection_id: "s",
      context: "Useful definition",
      mode: "treatment",
      reason: "selected",
    }),
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
  return { selector, api, sessions, context };
}

describe("Pi context selection", () => {
  it.each([false, true])(
    "discards uncertain registrations before native commands (split UTF-8 %s)",
    async (split) => {
      const { selector, api, context } = fixture();
      const text = "activation 🌽";
      selector.register("uncertain", text);
      const input = new PassThrough();
      observeContextSelectionFallback(input, selector);
      expect(input.readableFlowing).not.toBe(true);
      const nativeReader = createInterface({ input });
      const delivery = new Promise<Awaited<ReturnType<typeof context>>>(
        (resolve) => {
          nativeReader.once("line", async () =>
            resolve(await context([user(text)])),
          );
        },
      );
      try {
        const command = Buffer.from(
          `${JSON.stringify({ type: "prompt", message: text, posthog_context_selection_disabled: true })}\r\n`,
        );
        const boundary = split
          ? command.indexOf(Buffer.from("🌽")) + 1
          : command.length;
        input.write(command.subarray(0, boundary));
        input.write(command.subarray(boundary));
        expect((await delivery)?.messages).toEqual([user(text)]);
        selector.register("late-registration", "another request");
        await context([user("another request", 2)]);
        expect(api.prepareContextSelection).not.toHaveBeenCalled();
      } finally {
        nativeReader.close();
        input.destroy();
      }
    },
  );

  it("drops context prepared while selection is being disabled", async () => {
    const { selector, api, context } = fixture();
    const prepared =
      Promise.withResolvers<
        Awaited<ReturnType<PostHogAPIClient["prepareContextSelection"]>>
      >();
    api.prepareContextSelection.mockReturnValueOnce(prepared.promise);
    selector.register("human-1", "activation");
    const pending = context([user("activation")]);
    selector.disable();
    prepared.resolve({
      selection_id: "s",
      context: "Useful definition",
      mode: "treatment",
      reason: "selected",
    });
    expect((await pending)?.messages).toEqual([user("activation")]);
  });
  it("injects hidden native context once when the registered human prompt reaches the model", async () => {
    const { selector, api, context } = fixture();
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
    expect((await context(messages))?.messages).toEqual(result?.messages);
    expect(api.prepareContextSelection).toHaveBeenCalledTimes(1);
  });

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

  it("does not consume another request ID after preparation fails", async () => {
    const { selector, api, context } = fixture();
    selector.register("human-1", "activation");
    api.prepareContextSelection.mockRejectedValueOnce(new Error("offline"));
    const messages = [user("activation", 1)];
    expect((await context(messages))?.messages).toEqual(messages);
    selector.register("human-2", "activation");
    await context(messages);
    expect(api.prepareContextSelection).toHaveBeenCalledTimes(1);
    await context([...messages, user("activation", 2)]);
    expect(api.prepareContextSelection).toHaveBeenLastCalledWith(
      expect.objectContaining({ message_id: "human-2" }),
    );
  });
});
