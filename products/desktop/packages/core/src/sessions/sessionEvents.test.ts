import type { ContentBlock } from "@agentclientprotocol/sdk";
import type {
  AcpMessage,
  OptimisticItem,
  StoredLogEntry,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";

import { makeAttachmentUri } from "./promptContent";
import {
  collapseSupersededToolCallUpdates,
  convertStoredEntriesToEvents,
  dropEventsCoveredByTail,
  extractUserPromptsFromEvents,
  hasSessionPromptEvent,
  hasSessionPromptEventForTaskRun,
  isAbsoluteFolderPath,
  isFatalSessionError,
  promptReferencesAbsoluteFolder,
  selectEchoedOptimisticItemIds,
  selectUnseededPendingFollowups,
} from "./sessionEvents";

describe("isFatalSessionError", () => {
  it("detects fatal 'Internal error' pattern", () => {
    expect(isFatalSessionError("Internal error: process crashed")).toBe(true);
  });

  it("detects fatal 'process exited' pattern", () => {
    expect(isFatalSessionError("process exited with code 1")).toBe(true);
  });

  it("detects fatal 'Session not found' pattern", () => {
    expect(isFatalSessionError("Session not found")).toBe(true);
  });

  it("detects fatal 'Session did not end' pattern", () => {
    expect(isFatalSessionError("Session did not end cleanly")).toBe(true);
  });

  it("detects fatal 'not ready for writing' pattern", () => {
    expect(isFatalSessionError("not ready for writing")).toBe(true);
  });

  it("detects fatal pattern in errorDetails", () => {
    expect(isFatalSessionError("Unknown error", "Internal error: boom")).toBe(
      true,
    );
  });

  it("returns false for non-fatal errors", () => {
    expect(isFatalSessionError("Network timeout")).toBe(false);
  });

  it("returns false for empty string", () => {
    expect(isFatalSessionError("")).toBe(false);
  });
});

function promptEvent(prompt: ContentBlock[], ts = 1): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id: ts,
      method: "session/prompt",
      params: { prompt },
    },
  };
}

describe("extractUserPromptsFromEvents", () => {
  it("extracts text from a plain text prompt", () => {
    const events = [promptEvent([{ type: "text", text: "fix the bug" }])];
    expect(extractUserPromptsFromEvents(events)).toEqual(["fix the bug"]);
  });

  it("skips hidden text blocks", () => {
    const events = [
      promptEvent([
        {
          type: "text",
          text: "hidden context",
          _meta: { ui: { hidden: true } },
        } as ContentBlock,
        { type: "text", text: "visible prompt" },
      ]),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual(["visible prompt"]);
  });

  it("returns attachment labels when prompt has no text", () => {
    const uri = makeAttachmentUri("/tmp/screenshot.png");
    const events = [
      promptEvent([
        {
          type: "resource",
          resource: { uri, text: "", mimeType: "image/png" },
        },
      ]),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual([
      "[Attached files: screenshot.png]",
    ]);
  });

  it("returns text when prompt has both text and attachments", () => {
    const uri = makeAttachmentUri("/tmp/data.csv");
    const events = [
      promptEvent([
        { type: "text", text: "analyze this" },
        { type: "resource", resource: { uri, text: "", mimeType: "text/csv" } },
      ]),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual(["analyze this"]);
  });

  it("joins multiple attachment labels with commas", () => {
    const uri1 = makeAttachmentUri("/tmp/a.png");
    const uri2 = makeAttachmentUri("/tmp/b.pdf");
    const events = [
      promptEvent([
        {
          type: "resource",
          resource: { uri: uri1, text: "", mimeType: "image/png" },
        },
        {
          type: "resource",
          resource: { uri: uri2, text: "", mimeType: "application/pdf" },
        },
      ]),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual([
      "[Attached files: a.png, b.pdf]",
    ]);
  });

  it("falls back to attachment labels when all text blocks are hidden", () => {
    const uri = makeAttachmentUri("/tmp/report.md");
    const events = [
      promptEvent([
        {
          type: "text",
          text: "hidden",
          _meta: { ui: { hidden: true } },
        } as ContentBlock,
        {
          type: "resource",
          resource: { uri, text: "", mimeType: "text/markdown" },
        },
      ]),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual([
      "[Attached files: report.md]",
    ]);
  });

  it("skips events with empty prompt arrays", () => {
    const events = [promptEvent([])];
    expect(extractUserPromptsFromEvents(events)).toEqual([]);
  });

  it("collects prompts from multiple events in order", () => {
    const uri = makeAttachmentUri("/tmp/logo.svg");
    const events = [
      promptEvent([{ type: "text", text: "first" }], 1),
      promptEvent(
        [
          {
            type: "resource",
            resource: { uri, text: "", mimeType: "image/svg+xml" },
          },
        ],
        2,
      ),
      promptEvent([{ type: "text", text: "third" }], 3),
    ];
    expect(extractUserPromptsFromEvents(events)).toEqual([
      "first",
      "[Attached files: logo.svg]",
      "third",
    ]);
  });
});

describe("hasSessionPromptEvent", () => {
  const promptRequest: AcpMessage = {
    type: "acp_message",
    ts: 1,
    message: { jsonrpc: "2.0", id: 1, method: "session/prompt", params: {} },
  };
  const notification: AcpMessage = {
    type: "acp_message",
    ts: 2,
    message: { jsonrpc: "2.0", method: "session/update", params: {} },
  };

  it("is true when a session/prompt request is present", () => {
    expect(hasSessionPromptEvent([notification, promptRequest])).toBe(true);
  });

  it("is false when no session/prompt request is present", () => {
    expect(hasSessionPromptEvent([notification])).toBe(false);
    expect(hasSessionPromptEvent([])).toBe(false);
  });

  it("does not attribute an ancestor prompt to a resumed run", () => {
    const storedEntry = (event: AcpMessage): StoredLogEntry => ({
      type: "notification",
      timestamp: new Date(event.ts).toISOString(),
      notification: event.message,
    });
    const leafPrompt = {
      ...promptRequest,
      ts: 3,
      message: { ...promptRequest.message, id: 2 },
    };
    const events = convertStoredEntriesToEvents(
      [
        storedEntry(promptRequest),
        storedEntry(notification),
        storedEntry(leafPrompt),
      ],
      undefined,
      {
        taskRunId: "resume-run",
        startEntryIndex: 0,
        firstPositionedEntryIndex: 2,
      },
    );

    expect(
      hasSessionPromptEventForTaskRun(events.slice(0, 2), "resume-run"),
    ).toBe(false);
    expect(hasSessionPromptEventForTaskRun(events, "resume-run")).toBe(true);
  });
});

describe("selectEchoedOptimisticItemIds", () => {
  // The floor is compared against stored-log positions, so the events have to
  // be built the way a cloud commit builds them rather than by hand.
  const promptLog = (...texts: string[]): AcpMessage[] =>
    convertStoredEntriesToEvents(
      texts.map((text) => ({
        type: "notification",
        notification: {
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text }] },
        },
      })) as StoredLogEntry[],
      undefined,
      { taskRunId: "run-1", startEntryIndex: 0 },
    );
  const tailItem = (id: string, content: string): OptimisticItem => ({
    type: "user_message",
    id,
    content,
    timestamp: 1,
    pinToTop: false,
  });

  it("keeps a bubble the events carry no echo for", () => {
    expect(
      selectEchoedOptimisticItemIds(
        [tailItem("o1", "steer me")],
        promptLog("the original task"),
        0,
      ),
    ).toEqual([]);
  });

  it("drops a bubble once its echo lands", () => {
    expect(
      selectEchoedOptimisticItemIds(
        [tailItem("o1", "steer me")],
        promptLog("the original task", "steer me"),
        0,
      ),
    ).toEqual(["o1"]);
  });

  it("matches an echo that omits the bubble's attachment summary", () => {
    expect(
      selectEchoedOptimisticItemIds(
        [tailItem("o1", "look at this\n\nAttached files: notes.txt")],
        promptLog("look at this"),
        0,
      ),
    ).toEqual(["o1"]);
  });

  it("leaves a pinned bubble for the merge layer to dedupe", () => {
    const pinned: OptimisticItem = {
      type: "user_message",
      id: "o1",
      content: "the original task",
      timestamp: 1,
    };
    expect(
      selectEchoedOptimisticItemIds(
        [pinned],
        promptLog("the original task"),
        0,
      ),
    ).toEqual([]);
  });

  it("keeps a bubble whose repeated text only matches an already-committed prompt", () => {
    expect(
      selectEchoedOptimisticItemIds(
        [tailItem("o1", "yes")],
        promptLog("yes", "carry on"),
        2,
      ),
    ).toEqual([]);
  });

  it("retires one bubble per echo when several share the same text", () => {
    expect(
      selectEchoedOptimisticItemIds(
        [tailItem("o1", "yes"), tailItem("o2", "yes")],
        promptLog("yes"),
        0,
      ),
    ).toEqual(["o1"]);
  });
});

describe("selectUnseededPendingFollowups", () => {
  const promptLog = (...texts: string[]): AcpMessage[] =>
    convertStoredEntriesToEvents(
      texts.map((text) => ({
        type: "notification",
        notification: {
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text }] },
        },
      })) as StoredLogEntry[],
      undefined,
      { taskRunId: "run-1", startEntryIndex: 0 },
    );
  const tailItem = (id: string, content: string): OptimisticItem => ({
    type: "user_message",
    id,
    content,
    timestamp: 1,
    pinToTop: false,
  });

  it("seeds a message the log has no prompt for", () => {
    expect(
      selectUnseededPendingFollowups(
        [{ id: "m1", content: "check the paste path" }],
        promptLog("the original task"),
        [],
      ),
    ).toEqual([{ id: "m1", content: "check the paste path" }]);
  });

  it("skips a message the sandbox has already prompted with", () => {
    expect(
      selectUnseededPendingFollowups(
        [{ id: "m1", content: "check the paste path" }],
        promptLog("the original task", "check the paste path"),
        [],
      ),
    ).toEqual([]);
  });

  it("skips a message an optimistic bubble already shows", () => {
    expect(
      selectUnseededPendingFollowups(
        [{ id: "m1", content: "check the paste path" }],
        promptLog("the original task"),
        [tailItem("o1", "check the paste path")],
      ),
    ).toEqual([]);
  });

  it("seeds one message per uncovered copy when several share text", () => {
    expect(
      selectUnseededPendingFollowups(
        [
          { id: "m1", content: "yes" },
          { id: "m2", content: "yes" },
        ],
        promptLog("yes"),
        [],
      ),
    ).toEqual([{ id: "m2", content: "yes" }]);
  });

  it("matches a prompt that omits the message's attachment summary", () => {
    expect(
      selectUnseededPendingFollowups(
        [{ id: "m1", content: "look at this\n\nAttached files: notes.txt" }],
        promptLog("look at this"),
        [],
      ),
    ).toEqual([]);
  });

  const promptLogAt = (...prompts: [string, string][]): AcpMessage[] =>
    convertStoredEntriesToEvents(
      prompts.map(([text, timestamp]) => ({
        type: "notification",
        timestamp,
        notification: {
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text }] },
        },
      })) as StoredLogEntry[],
      undefined,
      { taskRunId: "run-1", startEntryIndex: 0 },
    );
  const repeated = { id: "m2", content: "yes", ts: "2026-08-26T15:00:00.000Z" };

  it("seeds a repeated message whose only matching prompt predates it", () => {
    expect(
      selectUnseededPendingFollowups(
        [repeated],
        promptLogAt(["yes", "2026-08-26T14:00:00.000Z"]),
        [],
      ),
    ).toEqual([repeated]);
  });

  it("skips a repeated message once a prompt lands after it", () => {
    expect(
      selectUnseededPendingFollowups(
        [repeated],
        promptLogAt(["yes", "2026-08-26T15:00:30.000Z"]),
        [],
      ),
    ).toEqual([]);
  });
});

describe("dropEventsCoveredByTail", () => {
  const noteEntry = (method: string): StoredLogEntry =>
    ({
      type: "notification",
      notification: { jsonrpc: "2.0", method },
    }) as unknown as StoredLogEntry;

  const positionedEvents = (
    taskRunId: string,
    startEntryIndex: number,
    methods: string[],
  ): AcpMessage[] =>
    convertStoredEntriesToEvents(methods.map(noteEntry), undefined, {
      taskRunId,
      startEntryIndex,
    });

  it("returns undefined when no existing event is covered by the tail", () => {
    const events = [
      ...positionedEvents("run-1", 0, ["a", "b"]),
      ...positionedEvents("other-run", 5, ["c"]),
      { type: "acp_message", ts: 1, message: {} } as unknown as AcpMessage,
    ];
    expect(dropEventsCoveredByTail(events, "run-1", 2)).toBeUndefined();
  });

  it("drops the run's events at or after the tail start and keeps the rest", () => {
    const kept = positionedEvents("run-1", 0, ["a", "b"]);
    const covered = positionedEvents("run-1", 3, ["c", "d"]);
    const otherRun = positionedEvents("other-run", 3, ["e"]);
    const unpositioned = {
      type: "acp_message",
      ts: 1,
      message: {},
    } as unknown as AcpMessage;
    const result = dropEventsCoveredByTail(
      [...kept, unpositioned, ...covered, ...otherRun],
      "run-1",
      3,
    );
    expect(result).toEqual([...kept, unpositioned, ...otherRun]);
  });
});

describe("convertStoredEntriesToEvents — imported user prompts", () => {
  const userChunkEntry = (
    text: string,
    meta?: Record<string, unknown>,
  ): StoredLogEntry =>
    ({
      timestamp: "2026-06-22T00:00:00.000Z",
      notification: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "user_message_chunk",
            content: { type: "text", text },
            ...(meta ? { _meta: meta } : {}),
          },
        },
      },
    }) as unknown as StoredLogEntry;

  it("promotes a marked imported user prompt into a session/prompt event", () => {
    const events = convertStoredEntriesToEvents([
      userChunkEntry("my earlier prompt", { importedUserPrompt: true }),
    ]);
    const msg = events[0].message;
    expect("method" in msg && msg.method).toBe("session/prompt");
    const params = (msg as { params?: { prompt?: ContentBlock[] } }).params;
    expect(params?.prompt?.[0]).toEqual({
      type: "text",
      text: "my earlier prompt",
    });
  });

  it("leaves an unmarked user_message_chunk as a raw notification", () => {
    const events = convertStoredEntriesToEvents([
      userChunkEntry("internal user content"),
    ]);
    const msg = events[0].message;
    expect("method" in msg && msg.method).toBe("session/update");
  });

  it("freezes converted events on both the promoted and raw branches", () => {
    const events = convertStoredEntriesToEvents([
      userChunkEntry("promoted", { importedUserPrompt: true }),
      userChunkEntry("raw"),
    ]);
    expect(events.every((event) => Object.isFrozen(event))).toBe(true);
  });
});

describe("isAbsoluteFolderPath", () => {
  it.each(["/Users/x/repo", "~/repo", "C:\\repo", "D:/repo"])(
    "treats %s as absolute",
    (path) => {
      expect(isAbsoluteFolderPath(path)).toBe(true);
    },
  );

  it.each(["repo", "./repo", "src/index.ts"])(
    "treats %s as not absolute",
    (path) => {
      expect(isAbsoluteFolderPath(path)).toBe(false);
    },
  );
});

describe("promptReferencesAbsoluteFolder", () => {
  it("detects an absolute folder tag in a string prompt", () => {
    expect(
      promptReferencesAbsoluteFolder('see <folder path="/Users/x/repo" />'),
    ).toBe(true);
  });

  it("returns false for a relative folder tag", () => {
    expect(
      promptReferencesAbsoluteFolder('see <folder path="src/lib" />'),
    ).toBe(false);
  });

  it("scans ContentBlock text for absolute folder tags", () => {
    const blocks: ContentBlock[] = [
      { type: "text", text: "intro" },
      { type: "text", text: '<folder path="~/work" />' },
    ];
    expect(promptReferencesAbsoluteFolder(blocks)).toBe(true);
  });

  it("returns false when no folder tag is present", () => {
    expect(promptReferencesAbsoluteFolder("just text")).toBe(false);
  });
});

describe("collapseSupersededToolCallUpdates", () => {
  const toolUpdateFields = (
    toolCallId: string,
    fields: Record<string, unknown>,
  ): AcpMessage =>
    ({
      type: "acp_message",
      ts: 1,
      message: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call_update",
            toolCallId,
            ...fields,
          },
        },
      },
    }) as unknown as AcpMessage;

  const toolUpdate = (toolCallId: string, text: string): AcpMessage =>
    toolUpdateFields(toolCallId, { content: text });

  const other = (text: string): AcpMessage =>
    ({
      type: "acp_message",
      ts: 1,
      message: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { type: "text", text },
          },
        },
      },
    }) as unknown as AcpMessage;

  // biome-ignore lint/suspicious/noExplicitAny: test introspection
  const sessionUpdate = (e: AcpMessage) => (e.message as any).params.update;

  it("collapses to one update per toolCallId, at the last update's position", () => {
    const events = [
      toolUpdate("a", "a1"),
      toolUpdate("a", "a2"),
      other("hi"),
      toolUpdate("a", "a3"),
    ];
    const collapsed = collapseSupersededToolCallUpdates(events);
    expect(collapsed).toHaveLength(2);
    expect(sessionUpdate(collapsed[0]).sessionUpdate).toBe(
      "agent_message_chunk",
    );
    expect(sessionUpdate(collapsed[1]).content).toBe("a3");
  });

  it("collapses each distinct toolCallId independently", () => {
    const events = [
      toolUpdate("a", "a1"),
      toolUpdate("b", "b1"),
      toolUpdate("a", "a2"),
      toolUpdate("b", "b2"),
    ];
    const collapsed = collapseSupersededToolCallUpdates(events);
    expect(collapsed.map((e) => sessionUpdate(e).content)).toEqual([
      "a2",
      "b2",
    ]);
  });

  it("leaves transcripts without tool updates untouched", () => {
    const events = [other("one"), other("two")];
    expect(collapseSupersededToolCallUpdates(events)).toBe(events);
  });

  it("merges fields across updates so nothing a replay would keep is lost", () => {
    // Mirrors the real emission shape: streamed rawInput snapshots, then an
    // input-complete update with title/content, then a terminal update that
    // carries only status/rawOutput.
    const events = [
      toolUpdateFields("a", { rawInput: { command: "ls" } }),
      toolUpdateFields("a", {
        rawInput: { command: "ls -la" },
        title: "List files",
        content: "input-derived",
      }),
      toolUpdateFields("a", { status: "completed", rawOutput: "done" }),
    ];
    const collapsed = collapseSupersededToolCallUpdates(events);
    expect(collapsed).toHaveLength(1);
    expect(sessionUpdate(collapsed[0])).toEqual({
      sessionUpdate: "tool_call_update",
      toolCallId: "a",
      rawInput: { command: "ls -la" },
      title: "List files",
      content: "input-derived",
      status: "completed",
      rawOutput: "done",
    });
  });

  it("later fields win when re-sent (matching the reducer's Object.assign)", () => {
    const events = [
      toolUpdateFields("a", { content: "stale", status: "in_progress" }),
      toolUpdateFields("a", { content: "fresh", status: "completed" }),
    ];
    const collapsed = collapseSupersededToolCallUpdates(events);
    expect(collapsed).toHaveLength(1);
    expect(sessionUpdate(collapsed[0]).content).toBe("fresh");
    expect(sessionUpdate(collapsed[0]).status).toBe("completed");
  });

  it("keeps a single-update call by reference, no synthetic clone", () => {
    const only = toolUpdate("a", "a1");
    const events = [other("hi"), only];
    const collapsed = collapseSupersededToolCallUpdates(events);
    expect(collapsed).toHaveLength(2);
    expect(collapsed[1]).toBe(only);
  });

  it("does not mutate the original (frozen) events when merging", () => {
    const first = toolUpdateFields("a", { rawInput: { command: "ls" } });
    const last = toolUpdateFields("a", { status: "completed" });
    Object.freeze(first);
    Object.freeze(last);
    const collapsed = collapseSupersededToolCallUpdates([first, last]);
    expect(sessionUpdate(first)).not.toHaveProperty("status");
    expect(sessionUpdate(last)).not.toHaveProperty("rawInput");
    expect(sessionUpdate(collapsed[0])).toHaveProperty("rawInput");
    expect(sessionUpdate(collapsed[0]).status).toBe("completed");
  });
});
