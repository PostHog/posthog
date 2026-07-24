import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { AcpMessage, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";

import { makeAttachmentUri } from "./promptContent";
import {
  collapseSupersededToolCallUpdates,
  convertStoredEntriesToEvents,
  extractUserPromptsFromEvents,
  hasSessionPromptEvent,
  isAbsoluteFolderPath,
  isFatalSessionError,
  promptReferencesAbsoluteFolder,
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
