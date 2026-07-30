import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PostHogAPIClient } from "./posthog-api";
import { SessionLogWriter } from "./session-log-writer";
import type { StoredNotification } from "./types";

function makeSessionUpdate(
  sessionUpdate: string,
  extra: Record<string, unknown> = {},
): string {
  return JSON.stringify({
    jsonrpc: "2.0",
    method: "session/update",
    params: { update: { sessionUpdate, ...extra } },
  });
}

describe("SessionLogWriter", () => {
  let logWriter: SessionLogWriter;
  let mockAppendLog: ReturnType<typeof vi.fn>;
  let mockPosthogAPI: PostHogAPIClient;

  beforeEach(() => {
    mockAppendLog = vi.fn().mockResolvedValue(undefined);
    mockPosthogAPI = {
      appendTaskRunLog: mockAppendLog,
    } as unknown as PostHogAPIClient;

    logWriter = new SessionLogWriter({ posthogAPI: mockPosthogAPI });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("appendRawLine", () => {
    it("queues entries for flush", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "test" }));
      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "test2" }));

      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(2);
    });

    it("ignores unregistered sessions", async () => {
      logWriter.appendRawLine("unknown", JSON.stringify({ method: "test" }));
      await logWriter.flush("unknown");
      expect(mockAppendLog).not.toHaveBeenCalled();
    });

    it("ignores invalid JSON", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, "not valid json {{{");
      await logWriter.flush(sessionId);
      expect(mockAppendLog).not.toHaveBeenCalled();
    });

    it("re-queues entries when persistence fails and retries", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      mockAppendLog
        .mockRejectedValueOnce(new Error("network error"))
        .mockResolvedValueOnce(undefined);

      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "test" }));

      await logWriter.flush(sessionId);
      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(2);
      const retriedEntries: StoredNotification[] =
        mockAppendLog.mock.calls[1][2];
      expect(retriedEntries).toHaveLength(1);
      expect(retriedEntries[0].notification.method).toBe("test");
    });

    it("drops entries after max retries", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      mockAppendLog.mockRejectedValue(new Error("persistent failure"));

      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "test" }));

      // Flush 10 times (MAX_FLUSH_RETRIES) — entries should be dropped on the 10th
      for (let i = 0; i < 10; i++) {
        await logWriter.flush(sessionId);
      }

      expect(mockAppendLog).toHaveBeenCalledTimes(10);

      // After max retries the entries are dropped, so an 11th flush has nothing
      mockAppendLog.mockClear();
      await logWriter.flush(sessionId);
      expect(mockAppendLog).not.toHaveBeenCalled();
    });
  });

  describe("sinks", () => {
    it("delivers non-chunk entries to sinks and keeps persistence when a sink throws", async () => {
      const goodSink = { append: vi.fn() };
      const badSink = {
        append: vi.fn(() => {
          throw new Error("sink down");
        }),
      };
      const writer = new SessionLogWriter({
        posthogAPI: mockPosthogAPI,
        sinks: [badSink, goodSink],
      });
      writer.register("run-1", { taskId: "task-1", runId: "run-1" });

      writer.appendRawLine(
        "run-1",
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "chunk" },
        }),
      );
      writer.appendRawLine(
        "run-1",
        JSON.stringify({
          jsonrpc: "2.0",
          method: "_posthog/turn_complete",
          params: { stopReason: "end_turn" },
        }),
      );

      // Buffered message chunks never reach sinks; the non-chunk entry does,
      // even after the sink listed first has thrown.
      expect(goodSink.append).toHaveBeenCalledTimes(1);
      expect(goodSink.append.mock.calls[0][0]).toBe("run-1");
      expect(goodSink.append.mock.calls[0][1].notification.method).toBe(
        "_posthog/turn_complete",
      );

      await writer.flush("run-1");

      const persistedMethods = mockAppendLog.mock.calls
        .flatMap((call) => call[2])
        .map((entry: StoredNotification) => entry.notification.method);
      expect(persistedMethods).toContain("_posthog/turn_complete");
    });
  });

  describe("agent_message_chunk coalescing", () => {
    it("coalesces consecutive chunks into a single agent_message", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "Hello " },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "world" },
        }),
      );
      // Non-chunk event triggers flush of chunks
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call", { toolCallId: "tc1" }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(2); // coalesced message + tool_call

      const coalesced = entries[0].notification;
      expect(coalesced.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "Hello world" },
      });
      expect(logWriter.getLastAgentMessage(sessionId)).toBe("Hello world");
    });

    it("tracks direct agent_message updates", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "Pick MIT or Apache" },
        }),
      );

      await logWriter.flush(sessionId);

      expect(logWriter.getLastAgentMessage(sessionId)).toBe(
        "Pick MIT or Apache",
      );
    });
  });

  describe("empty agent_thought_chunk filtering", () => {
    it.each([
      {
        kind: "empty text content",
        extra: { content: { type: "text", text: "" } },
      },
      {
        kind: "empty thinking content",
        extra: { content: { type: "thinking", thinking: "" } },
      },
      { kind: "no content", extra: {} },
    ])("does not persist thought chunks with $kind", async ({ extra }) => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_thought_chunk", extra),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_thought_chunk", {
          content: { type: "thinking", thinking: "planning the fix" },
        }),
      );

      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(1);
      expect(entries[0].notification.params?.update).toEqual({
        sessionUpdate: "agent_thought_chunk",
        content: { type: "thinking", thinking: "planning the fix" },
      });
    });

    it("keeps message chunks coalescing across an interleaved empty thought chunk", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "Hello " },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_thought_chunk", {
          content: { type: "text", text: "" },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "world" },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call", { toolCallId: "tc1" }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(2);
      expect(entries[0].notification.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "Hello world" },
      });
    });
  });

  describe("_doFlush does not prematurely coalesce", () => {
    it("does not coalesce buffered chunks during a timed flush", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      // Buffer some chunks (no non-chunk event to trigger coalescing)
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "Hello " },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "world" },
        }),
      );

      // Flush without any non-chunk event arriving — simulates
      // the 500ms debounce timer firing mid-stream
      await logWriter.flush(sessionId);

      // No entries should have been sent — chunks are still buffered
      expect(mockAppendLog).not.toHaveBeenCalled();

      // Now a non-chunk event arrives, triggering natural coalescing
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("usage_update", { used: 100 }),
      );

      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(2); // coalesced agent_message + usage_update
      const coalesced = entries[0].notification;
      expect(coalesced.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "Hello world" },
      });
    });
  });

  describe("flushAll coalesces on shutdown", () => {
    it("coalesces remaining chunks before flushing", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "partial response" },
        }),
      );

      await logWriter.flushAll();

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(1);
      const coalesced = entries[0].notification;
      expect(coalesced.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "partial response" },
      });
    });
  });

  describe("flush with coalesce option", () => {
    it("drains chunk buffer when coalesce is true", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "complete text" },
        }),
      );

      await logWriter.flush(sessionId, { coalesce: true });

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      const coalesced = entries[0].notification;
      expect(coalesced.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "complete text" },
      });
    });

    it("does not coalesce when coalesce is false", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "buffered" },
        }),
      );

      await logWriter.flush(sessionId, { coalesce: false });

      expect(mockAppendLog).not.toHaveBeenCalled();
    });
  });

  describe("direct agent_message supersedes chunks", () => {
    it("discards buffered chunks when a direct agent_message arrives", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      // Buffer partial chunks
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "partial " },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "text" },
        }),
      );

      // Direct agent_message arrives — authoritative full text
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "complete full response" },
        }),
      );

      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      // Only the direct agent_message — no coalesced partial entry
      expect(entries).toHaveLength(1);
      const coalesced = entries[0].notification;
      expect(coalesced.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "complete full response" },
      });
      expect(logWriter.getLastAgentMessage(sessionId)).toBe(
        "complete full response",
      );
    });

    it("is additive with earlier coalesced text in multi-message turns", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      // First assistant message: chunks coalesced by a tool_call event
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "first message" },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call", { toolCallId: "tc1" }),
      );
      // "first message" is now coalesced into currentTurnMessages

      // Second assistant message arrives as direct agent_message
      // (e.g., after tool result, no active chunk buffer)
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "second message" },
        }),
      );

      const response = logWriter.getFullAgentResponse(sessionId);
      // Both messages are preserved — direct message is additive
      expect(response).toBe("first message\n\nsecond message");
    });

    it("getAgentResponseParts returns each turn message as a separate entry", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "I'll pull DAU." },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call", { toolCallId: "tc1" }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "Here's your answer." },
        }),
      );

      // getFullAgentResponse still joins for backends without text_parts support.
      expect(logWriter.getFullAgentResponse(sessionId)).toBe(
        "I'll pull DAU.\n\nHere's your answer.",
      );
      // getAgentResponseParts keeps the split — the Slack relay picks the last.
      expect(logWriter.getAgentResponseParts(sessionId)).toEqual([
        "I'll pull DAU.",
        "Here's your answer.",
      ]);
    });

    it("getAgentResponseParts returns undefined for an empty/unregistered turn", () => {
      expect(
        logWriter.getAgentResponseParts("never-registered"),
      ).toBeUndefined();

      const sessionId = "empty";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });
      expect(logWriter.getAgentResponseParts(sessionId)).toBeUndefined();
    });

    it("persisted log does not contain stale entries when chunks are superseded", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      // Chunks buffered, then direct agent_message supersedes before coalescing
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message_chunk", {
          content: { type: "text", text: "partial" },
        }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "complete" },
        }),
      );

      await logWriter.flush(sessionId);

      expect(mockAppendLog).toHaveBeenCalledTimes(1);
      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      // Only the direct agent_message — no coalesced partial entry
      expect(entries).toHaveLength(1);
      const persisted = entries[0].notification;
      expect(persisted.params?.update).toEqual({
        sessionUpdate: "agent_message",
        content: { type: "text", text: "complete" },
      });
    });
  });

  describe("API-path rawInput snapshot coalescing", () => {
    function rawInputSnapshot(toolCallId: string, rawInput: unknown): string {
      return makeSessionUpdate("tool_call_update", { toolCallId, rawInput });
    }

    it("persists only the last cumulative snapshot, before the completing update", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call", {
          toolCallId: "tc1",
          status: "pending",
        }),
      );
      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", {}));
      logWriter.appendRawLine(
        sessionId,
        rawInputSnapshot("tc1", { command: "ls" }),
      );
      logWriter.appendRawLine(
        sessionId,
        rawInputSnapshot("tc1", { command: "ls -la" }),
      );
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call_update", {
          toolCallId: "tc1",
          status: "completed",
          rawOutput: { content: [] },
        }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(3);
      expect(entries[1].notification.params?.update).toEqual({
        sessionUpdate: "tool_call_update",
        toolCallId: "tc1",
        rawInput: { command: "ls -la" },
      });
      expect(
        (entries[2].notification.params?.update as { status?: string }).status,
      ).toBe("completed");
    });

    it("drops the buffered snapshot when a richer update carries rawInput itself", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { a: 1 }));
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call_update", {
          toolCallId: "tc1",
          title: "Execute command",
          kind: "execute",
          rawInput: { a: 1, b: 2 },
        }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(1);
      expect(entries[0].notification.params?.update).toEqual({
        sessionUpdate: "tool_call_update",
        toolCallId: "tc1",
        title: "Execute command",
        kind: "execute",
        rawInput: { a: 1, b: 2 },
      });
    });

    it("buffers interleaved tool calls independently", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { n: 1 }));
      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc2", { m: 1 }));
      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { n: 2 }));
      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc2", { m: 2 }));
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("tool_call_update", {
          toolCallId: "tc1",
          status: "completed",
          rawOutput: {},
        }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(2);
      expect(entries[0].notification.params?.update).toEqual({
        sessionUpdate: "tool_call_update",
        toolCallId: "tc1",
        rawInput: { n: 2 },
      });
    });

    it("does not emit buffered snapshots on a timed flush mid-stream", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { a: 1 }));

      await logWriter.flush(sessionId);

      expect(mockAppendLog).not.toHaveBeenCalled();
    });

    it.each([
      {
        drainVia: "flushAll",
        drain: (writer: SessionLogWriter) => writer.flushAll(),
      },
      {
        drainVia: "flush with coalesce",
        drain: (writer: SessionLogWriter) =>
          writer.flush("s1", { coalesce: true }),
      },
    ])(
      "drains buffered snapshots on $drainVia, keeping only the latest",
      async ({ drain }) => {
        const sessionId = "s1";
        logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

        logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { a: 1 }));
        logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { a: 2 }));

        await drain(logWriter);

        expect(mockAppendLog).toHaveBeenCalledTimes(1);
        const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
        expect(entries).toHaveLength(1);
        expect(entries[0].notification.params?.update).toEqual({
          sessionUpdate: "tool_call_update",
          toolCallId: "tc1",
          rawInput: { a: 2 },
        });
      },
    );

    it("keeps snapshots buffered while other events flow to the API", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      logWriter.appendRawLine(sessionId, rawInputSnapshot("tc1", { a: 1 }));
      logWriter.appendRawLine(
        sessionId,
        makeSessionUpdate("agent_message", {
          content: { type: "text", text: "still working" },
        }),
      );

      await logWriter.flush(sessionId);

      const entries: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      expect(entries).toHaveLength(1);
      expect(
        (entries[0].notification.params?.update as { sessionUpdate?: string })
          .sessionUpdate,
      ).toBe("agent_message");
    });
  });

  describe("register", () => {
    it("does not re-register existing sessions", () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });
      logWriter.register(sessionId, { taskId: "t2", runId: sessionId });

      expect(logWriter.isRegistered(sessionId)).toBe(true);
    });
  });

  describe("flush serialization", () => {
    it("serializes concurrent flush calls so they do not overlap", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      const callOrder: string[] = [];
      let resolveFirst!: () => void;
      const firstBlocked = new Promise<void>((r) => {
        resolveFirst = r;
      });

      mockAppendLog
        .mockImplementationOnce(async () => {
          callOrder.push("first-start");
          // Add a new entry while the first flush is in-flight
          logWriter.appendRawLine(sessionId, JSON.stringify({ method: "b" }));
          await firstBlocked;
          callOrder.push("first-end");
        })
        .mockImplementationOnce(async () => {
          callOrder.push("second-start");
        });

      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "a" }));
      const flush1 = logWriter.flush(sessionId);

      // Wait for the first flush to be in-flight — "b" is added inside the mock
      await vi.waitFor(() => expect(callOrder).toContain("first-start"));

      // Queue a second flush for the entry added while first was in-flight
      const flush2 = logWriter.flush(sessionId);

      // First flush is blocked — second should not have started
      expect(callOrder).not.toContain("second-start");

      // Unblock first flush
      resolveFirst?.();
      await flush1;
      await flush2;

      // Second started only after first completed
      expect(callOrder).toEqual(["first-start", "first-end", "second-start"]);
    });

    it("does not lose entries when flushes are serialized", async () => {
      const sessionId = "s1";
      logWriter.register(sessionId, { taskId: "t1", runId: sessionId });

      let resolveFirst!: () => void;
      const firstBlocked = new Promise<void>((r) => {
        resolveFirst = r;
      });

      mockAppendLog
        .mockImplementationOnce(async () => {
          // Add a new entry while the first flush is in-flight — simulates
          // the agent emitting end_turn while a scheduled flush is sending
          // earlier entries to S3.
          logWriter.appendRawLine(sessionId, JSON.stringify({ method: "b" }));
          await firstBlocked;
        })
        .mockImplementationOnce(async () => undefined);

      // Batch 1
      logWriter.appendRawLine(sessionId, JSON.stringify({ method: "a" }));
      const flush1 = logWriter.flush(sessionId);

      // Wait for first flush to be in-flight (and "b" to be added)
      await vi.waitFor(() => expect(mockAppendLog).toHaveBeenCalledTimes(1));

      // Queue flush for the entry added while first was in-flight
      const flush2 = logWriter.flush(sessionId);

      resolveFirst?.();
      await flush1;
      await flush2;

      expect(mockAppendLog).toHaveBeenCalledTimes(2);
      const batch1: StoredNotification[] = mockAppendLog.mock.calls[0][2];
      const batch2: StoredNotification[] = mockAppendLog.mock.calls[1][2];
      expect(batch1).toHaveLength(1);
      expect(batch1[0].notification.method).toBe("a");
      expect(batch2).toHaveLength(1);
      expect(batch2[0].notification.method).toBe("b");
    });
  });
});

describe("SessionLogWriter — local-cache tool_call_update coalescing", () => {
  let tmp: string;
  let writer: SessionLogWriter;
  const RUN = "run-coalesce";

  beforeEach(async () => {
    const fs = await import("node:fs");
    const os = await import("node:os");
    const path = await import("node:path");
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "slw-"));
    writer = new SessionLogWriter({ localCachePath: tmp });
    writer.register(RUN, { taskId: "t", runId: RUN });
  });

  afterEach(async () => {
    const fs = await import("node:fs");
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  const readLog = async (): Promise<Record<string, unknown>[]> => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const p = path.join(tmp, "sessions", RUN, "logs.ndjson");
    if (!fs.existsSync(p)) return [];
    return fs
      .readFileSync(p, "utf-8")
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((l) => JSON.parse(l));
  };

  const update = (extra: Record<string, unknown>) =>
    makeSessionUpdate("tool_call_update", { toolCallId: "a", ...extra });

  const sessionUpdateOf = (e: Record<string, unknown>) =>
    // biome-ignore lint/suspicious/noExplicitAny: test introspection
    (e.notification as any).params.update;

  it("writes one merged update per call, flushed by a non-tool event", async () => {
    writer.appendRawLine(RUN, update({ content: "a1" }));
    writer.appendRawLine(RUN, update({ content: "a2" }));
    writer.appendRawLine(RUN, update({ content: "a3" }));
    // a non-tool event flushes the buffered union, then writes itself
    writer.appendRawLine(RUN, makeSessionUpdate("agent_message"));

    const log = await readLog();
    expect(log).toHaveLength(2);
    expect(sessionUpdateOf(log[0]).content).toBe("a3");
    expect(sessionUpdateOf(log[1]).sessionUpdate).toBe("agent_message");
  });

  it("a terminal update merges into buffered snapshots, later fields winning", async () => {
    writer.appendRawLine(RUN, update({ content: "a1" }));
    writer.appendRawLine(RUN, update({ content: "a2" }));
    writer.appendRawLine(
      RUN,
      update({ content: "final", status: "completed" }),
    );

    const log = await readLog();
    expect(log).toHaveLength(1);
    expect(sessionUpdateOf(log[0]).content).toBe("final");
    expect(sessionUpdateOf(log[0]).status).toBe("completed");
  });

  it("fields carried only by earlier updates survive the terminal write", async () => {
    // Mirrors the real emission shape: streamed rawInput snapshots carry the
    // input, the terminal update carries only status/rawOutput.
    writer.appendRawLine(RUN, update({ rawInput: { command: "ls" } }));
    writer.appendRawLine(
      RUN,
      update({ rawInput: { command: "ls -la" }, title: "List files" }),
    );
    writer.appendRawLine(
      RUN,
      update({ status: "completed", rawOutput: "done" }),
    );

    const log = await readLog();
    expect(log).toHaveLength(1);
    expect(sessionUpdateOf(log[0])).toMatchObject({
      toolCallId: "a",
      rawInput: { command: "ls -la" },
      title: "List files",
      status: "completed",
      rawOutput: "done",
    });
  });

  it("keeps the final snapshot and terminal update on the API path, unmutated by the merge", async () => {
    const appendLog = vi.fn().mockResolvedValue(undefined);
    const apiWriter = new SessionLogWriter({
      localCachePath: tmp,
      posthogAPI: { appendTaskRunLog: appendLog } as never,
    });
    const API_RUN = "run-api";
    apiWriter.register(API_RUN, { taskId: "t", runId: API_RUN });

    apiWriter.appendRawLine(
      API_RUN,
      makeSessionUpdate("tool_call_update", {
        toolCallId: "a",
        rawInput: { command: "ls" },
      }),
    );
    apiWriter.appendRawLine(
      API_RUN,
      makeSessionUpdate("tool_call_update", {
        toolCallId: "a",
        status: "completed",
      }),
    );
    await apiWriter.flush(API_RUN);

    // The durable log receives both updates as emitted; the buffered merge
    // must build its own object rather than write into the shared entries.
    const entries = appendLog.mock.calls[0][2] as {
      notification: { params: { update: Record<string, unknown> } };
    }[];
    expect(entries).toHaveLength(2);
    expect(entries[0].notification.params.update).toEqual({
      sessionUpdate: "tool_call_update",
      toolCallId: "a",
      rawInput: { command: "ls" },
    });
    expect(entries[1].notification.params.update).toEqual({
      sessionUpdate: "tool_call_update",
      toolCallId: "a",
      status: "completed",
    });
  });

  it("flushAll persists a still-buffered merged update", async () => {
    writer.appendRawLine(RUN, update({ rawInput: { command: "ls" } }));
    writer.appendRawLine(RUN, update({ content: "a2" }));
    await writer.flushAll();

    const log = await readLog();
    expect(log).toHaveLength(1);
    expect(sessionUpdateOf(log[0]).content).toBe("a2");
    expect(sessionUpdateOf(log[0]).rawInput).toEqual({ command: "ls" });
  });

  it("hold-window flush writes the union so far and starts a new window", async () => {
    vi.useFakeTimers();
    try {
      writer.appendRawLine(RUN, update({ rawInput: { command: "ls" } }));
      vi.advanceTimersByTime(2500);
      // Exceeds TOOL_UPDATE_MAX_HOLD_MS: the buffered union is written, this
      // update starts a fresh window.
      writer.appendRawLine(RUN, update({ content: "partial" }));
      writer.appendRawLine(
        RUN,
        update({ status: "completed", rawOutput: "done" }),
      );

      const log = await readLog();
      expect(log).toHaveLength(2);
      expect(sessionUpdateOf(log[0]).rawInput).toEqual({ command: "ls" });
      // The second line unions the post-window snapshot with the terminal
      // update; a merge-on-read of both lines rebuilds the full call state.
      expect(sessionUpdateOf(log[1]).content).toBe("partial");
      expect(sessionUpdateOf(log[1]).status).toBe("completed");
      expect(sessionUpdateOf(log[1]).rawOutput).toBe("done");
    } finally {
      vi.useRealTimers();
    }
  });
});
