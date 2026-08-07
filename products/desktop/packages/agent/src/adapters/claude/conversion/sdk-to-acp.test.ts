import type {
  AgentSideConnection,
  SessionNotification,
} from "@agentclientprotocol/sdk";
import type {
  SDKAssistantMessage,
  SDKModelRefusalFallbackMessage,
  SDKPartialAssistantMessage,
  SDKUserMessage,
} from "@anthropic-ai/claude-agent-sdk";
import { describe, expect, it } from "vitest";
import { Logger } from "../../../utils/logger";
import type { Session } from "../types";
import {
  handleStreamEvent,
  handleSystemMessage,
  handleUserAssistantMessage,
  type MessageHandlerContext,
  stripMarkerTags,
} from "./sdk-to-acp";

describe("stripMarkerTags", () => {
  it("strips a single marker and keeps surrounding prose", () => {
    expect(
      stripMarkerTags("before<command-name>/model</command-name>after"),
    ).toBe("beforeafter");
  });

  it("strips multiple different markers in one pass", () => {
    const input =
      "a<command-args>x</command-args>b<local-command-stdout>out</local-command-stdout>c";
    expect(stripMarkerTags(input)).toBe("abc");
  });

  it("leaves text without markers unchanged", () => {
    expect(stripMarkerTags("")).toBe("");
    expect(stripMarkerTags("plain prose with < and > but no tags")).toBe(
      "plain prose with < and > but no tags",
    );
  });

  it("passes an unclosed opener through verbatim (dead-set path)", () => {
    const input = "<command-name>no closing tag, prose continues";
    expect(stripMarkerTags(input)).toBe(input);
  });

  it("does not treat an orphan closing tag as an opener", () => {
    expect(
      stripMarkerTags("</command-name>text<command-name>real</command-name>"),
    ).toBe("</command-name>text");
  });

  it("matches the nearest closing tag for a repeated opener", () => {
    expect(
      stripMarkerTags(
        "<command-name>outer<command-name>inner</command-name>trailing",
      ),
    ).toBe("trailing");
  });

  it("stays linear on pathological unclosed input", () => {
    const input = `${"<command-name>".repeat(20000)}tail`;
    expect(stripMarkerTags(input)).toBe(input);
  });
});

function createHandlerContext() {
  const updates: SessionNotification[] = [];
  const notifications: Array<{ method: string; params: unknown }> = [];
  const client = {
    sessionUpdate: async (notification: SessionNotification) => {
      updates.push(notification);
    },
    extNotification: async (method: string, params: unknown) => {
      notifications.push({ method, params });
    },
  } as unknown as AgentSideConnection;
  const context: MessageHandlerContext = {
    session: {
      cwd: "/test",
      taskState: new Map(),
      notificationHistory: [],
    } as unknown as Session,
    sessionId: "test-session",
    client,
    toolUseCache: {},
    toolUseStreamCache: new Map(),
    fileContentCache: {},
    logger: new Logger({ debug: false }),
    streamedAssistantBlocks: { blocks: [] },
  };
  return { context, updates, notifications };
}

function streamEvent(
  event: Record<string, unknown>,
  parentToolUseId: string | null = null,
): SDKPartialAssistantMessage {
  return {
    type: "stream_event",
    parent_tool_use_id: parentToolUseId,
    uuid: "00000000-0000-0000-0000-000000000001",
    session_id: "test-session",
    event,
  } as unknown as SDKPartialAssistantMessage;
}

function assistantMessage(
  apiId: string,
  content: Array<Record<string, unknown>>,
  parentToolUseId: string | null = null,
): SDKAssistantMessage {
  return {
    type: "assistant",
    parent_tool_use_id: parentToolUseId,
    uuid: "00000000-0000-0000-0000-000000000002",
    session_id: "test-session",
    message: {
      id: apiId,
      role: "assistant",
      content,
    },
  } as unknown as SDKAssistantMessage;
}

function chunkTexts(
  updates: SessionNotification[],
  type: "agent_message_chunk" | "agent_thought_chunk",
): string[] {
  return updates
    .filter((u) => u.update.sessionUpdate === type)
    .map((u) => (u.update as { content: { text: string } }).content.text);
}

async function streamLiveText(
  context: MessageHandlerContext,
  apiId: string,
  text: string,
): Promise<void> {
  await handleStreamEvent(
    streamEvent({ type: "message_start", message: { id: apiId } }),
    context,
  );
  await handleStreamEvent(
    streamEvent({
      type: "content_block_delta",
      index: 0,
      delta: { type: "text_delta", text },
    }),
    context,
  );
}

describe("assembled assistant text fallback", () => {
  it("forwards assembled text that never streamed", async () => {
    const { context, updates } = createHandlerContext();
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "full answer" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual(["full answer"]);
  });

  it("drops assembled text that already streamed live", async () => {
    const { context, updates } = createHandlerContext();
    await streamLiveText(context, "msg_1", "streamed");
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "streamed" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
  });

  it("forwards un-streamed thinking when only text streamed", async () => {
    const { context, updates } = createHandlerContext();
    await streamLiveText(context, "msg_1", "streamed");
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [
        { type: "thinking", thinking: "private reasoning" },
        { type: "text", text: "streamed" },
      ]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
    expect(chunkTexts(updates, "agent_thought_chunk")).toEqual([
      "private reasoning",
    ]);
  });

  it("tracks streamed content per message so a later message still falls back", async () => {
    const { context, updates } = createHandlerContext();
    await streamLiveText(context, "msg_1", "streamed");
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage("msg_2", [{ type: "text", text: "not streamed" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([
      "not streamed",
    ]);
  });

  it.each([
    {
      label: "forwards only the un-streamed tail when the stream was cut short",
      streams: [["msg_1", "hello wor"]] as const,
      assembled: { id: "msg_1", text: "hello world" },
      expected: ["ld"],
    },
    {
      label:
        "dedupes by content when the consolidated message id differs from the stream",
      streams: [["msg_gateway_1", "same text"]] as const,
      assembled: { id: "msg_other_id", text: "same text" },
      expected: [],
    },
    {
      // msg_1 never got its consolidated message (e.g. cancelled turn);
      // its residue must not swallow or truncate msg_2's block.
      label: "clears streamed residue when a new top-level message starts",
      streams: [
        ["msg_1", "cancelled turn text"],
        ["msg_2", "cancelled"],
      ] as const,
      assembled: { id: "msg_2", text: "cancelled turn" },
      expected: [" turn"],
    },
  ])("$label", async ({ streams, assembled, expected }) => {
    const { context, updates } = createHandlerContext();
    for (const [apiId, text] of streams) {
      await streamLiveText(context, apiId, text);
    }
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage(assembled.id, [{ type: "text", text: assembled.text }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual(expected);
  });

  it("ignores empty streamed deltas so they cannot stall the diff cursor", async () => {
    const { context, updates } = createHandlerContext();
    await handleStreamEvent(
      streamEvent({ type: "message_start", message: { id: "msg_1" } }),
      context,
    );
    await handleStreamEvent(
      streamEvent({
        type: "content_block_delta",
        index: 0,
        delta: { type: "thinking_delta", thinking: "" },
      }),
      context,
    );
    await handleStreamEvent(
      streamEvent({
        type: "content_block_delta",
        index: 1,
        delta: { type: "text_delta", text: "answer" },
      }),
      context,
    );
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [
        { type: "thinking", thinking: "" },
        { type: "text", text: "answer" },
      ]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
    expect(chunkTexts(updates, "agent_thought_chunk")).toEqual([]);
  });

  it("drops empty assembled blocks", async () => {
    const { context, updates } = createHandlerContext();
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [
        { type: "thinking", thinking: "" },
        { type: "text", text: "" },
      ]),
      context,
    );
    expect(updates).toEqual([]);
  });

  it("always drops subagent assistant text", async () => {
    const { context, updates } = createHandlerContext();
    await handleUserAssistantMessage(
      assistantMessage(
        "msg_1",
        [{ type: "text", text: "subagent prose" }],
        "tool_1",
      ),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
  });

  it("does not record deltas from subagent streams", async () => {
    const { context, updates } = createHandlerContext();
    await handleStreamEvent(
      streamEvent({ type: "message_start", message: { id: "msg_1" } }),
      context,
    );
    await handleStreamEvent(
      streamEvent(
        {
          type: "content_block_delta",
          index: 0,
          delta: { type: "text_delta", text: "subagent" },
        },
        "tool_1",
      ),
      context,
    );
    updates.length = 0;
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "top-level answer" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([
      "top-level answer",
    ]);
  });

  it("keeps the legacy drop-all filter without a tracker (replay)", async () => {
    const { context, updates } = createHandlerContext();
    context.streamedAssistantBlocks = undefined;
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "replayed" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
  });
});

function userMessage(
  content: string | Array<Record<string, unknown>>,
): SDKUserMessage {
  return {
    type: "user",
    parent_tool_use_id: null,
    uuid: "00000000-0000-0000-0000-000000000003",
    session_id: "test-session",
    message: { role: "user", content },
  } as unknown as SDKUserMessage;
}

function userChunkTexts(updates: SessionNotification[]): string[] {
  return updates
    .filter((u) => u.update.sessionUpdate === "user_message_chunk")
    .map((u) => (u.update as { content: { text: string } }).content.text);
}

describe("import replay (no client-side history)", () => {
  function createImportReplayContext() {
    const { context, updates } = createHandlerContext();
    context.streamedAssistantBlocks = undefined;
    context.isImportReplay = true;
    return { context, updates };
  }

  it("forwards top-level assistant text during import replay", async () => {
    const { context, updates } = createImportReplayContext();
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "replayed answer" }]),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([
      "replayed answer",
    ]);
  });

  it("emits and marks plain-text user prompts during import replay", async () => {
    const { context, updates } = createImportReplayContext();
    await handleUserAssistantMessage(userMessage("my earlier prompt"), context);
    expect(userChunkTexts(updates)).toEqual(["my earlier prompt"]);
    const chunk = updates.find(
      (u) => u.update.sessionUpdate === "user_message_chunk",
    );
    expect(
      (chunk?.update as { _meta?: { importedUserPrompt?: boolean } })._meta
        ?.importedUserPrompt,
    ).toBe(true);
  });

  it.each([
    {
      name: "with args",
      raw: "<command-message>review</command-message>\n<command-name>/review</command-name>\n<command-args>#2198 - findings first</command-args>",
      expected: "/review #2198 - findings first",
    },
    {
      name: "no args",
      raw: "<command-message>compact</command-message>\n<command-name>/compact</command-name>\n<command-args></command-args>",
      expected: "/compact",
    },
  ])(
    "surfaces a typed slash command ($name), not its raw markers",
    async ({ raw, expected }) => {
      const { context, updates } = createImportReplayContext();
      await handleUserAssistantMessage(userMessage(raw), context);
      expect(userChunkTexts(updates)).toEqual([expected]);
    },
  );

  it("strips stray markers from a non-command prompt instead of leaking them", async () => {
    const { context, updates } = createImportReplayContext();
    await handleUserAssistantMessage(
      userMessage("note <command-args>stray</command-args>"),
      context,
    );
    const [text] = userChunkTexts(updates);
    expect(text).not.toContain("<command-args>");
    expect(text).toContain("note");
  });

  it("skips a pure-marker user prompt instead of emitting a hollow chunk", async () => {
    const { context, updates } = createImportReplayContext();
    await handleUserAssistantMessage(
      userMessage("<command-args>stray</command-args>"),
      context,
    );
    expect(userChunkTexts(updates)).toEqual([]);
  });

  it("still drops subagent assistant text during import replay", async () => {
    const { context, updates } = createImportReplayContext();
    await handleUserAssistantMessage(
      assistantMessage("msg_1", [{ type: "text", text: "subagent" }], "tool_1"),
      context,
    );
    expect(chunkTexts(updates, "agent_message_chunk")).toEqual([]);
  });
});

describe("handleSystemMessage model_refusal_fallback", () => {
  function refusalFallbackMessage(
    overrides: Partial<SDKModelRefusalFallbackMessage> = {},
  ): SDKModelRefusalFallbackMessage {
    return {
      type: "system",
      subtype: "model_refusal_fallback",
      trigger: "refusal",
      direction: "retry",
      original_model: "claude-fable-5",
      fallback_model: "claude-opus-4-8",
      request_id: "req_1",
      api_refusal_category: "cyber",
      api_refusal_explanation: "This request was declined.",
      retracted_message_uuids: [],
      content: "Retried on fallback model",
      uuid: "00000000-0000-0000-0000-000000000009",
      session_id: "test-session",
      ...overrides,
    };
  }

  it.each<
    [string, Partial<SDKModelRefusalFallbackMessage>, Record<string, unknown>]
  >([
    [
      "emits a refusal_fallback status notification with the model swap",
      {},
      {
        sessionId: "test-session",
        status: "refusal_fallback",
        fromModel: "claude-fable-5",
        toModel: "claude-opus-4-8",
        explanation: "This request was declined.",
      },
    ],
    [
      "omits the explanation when the refused response carried none",
      { api_refusal_explanation: null },
      {
        sessionId: "test-session",
        status: "refusal_fallback",
        fromModel: "claude-fable-5",
        toModel: "claude-opus-4-8",
      },
    ],
  ])("%s", async (_name, overrides, expectedParams) => {
    const { context, updates, notifications } = createHandlerContext();

    await handleSystemMessage(refusalFallbackMessage(overrides), context);

    expect(updates).toEqual([]);
    expect(notifications).toEqual([
      { method: "_posthog/status", params: expectedParams },
    ]);
  });

  it.each(["revert", "sticky"] as const)(
    "skips the notification for the legacy %s direction",
    async (direction) => {
      const { context, notifications } = createHandlerContext();

      await handleSystemMessage(refusalFallbackMessage({ direction }), context);

      expect(notifications).toEqual([]);
    },
  );
});
