import type { AcpMessage, StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { convertStoredEntriesToEvents } from "./sessionEvents";
import { reconcileLiveEventsWithHydratedEvents } from "./sessionService";

function prompt(id: number, text: string, ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text }] },
    },
  };
}

function agentMessage(text: string, ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message",
          content: { type: "text", text },
        },
      },
    },
  };
}

function agentMessageChunk(text: string, ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  };
}

function toolCall(toolCallId: string, ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "tool_call",
          toolCallId,
          title: "Run command",
          kind: "execute",
          status: "completed",
        },
      },
    },
  };
}

function turnComplete(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/turn_complete",
      params: { stopReason: "end_turn" },
    },
  };
}

function storedEntry(event: AcpMessage): StoredLogEntry {
  return {
    type: "notification",
    timestamp: new Date(event.ts).toISOString(),
    notification: event.message,
  };
}

describe("resume hydration reconciliation", () => {
  it("discards a stale completed tail from an earlier leaf turn", () => {
    const firstResponse = agentMessage("first response", 20);
    const firstCompletion = turnComplete(30);
    const hydratedEvents = [
      prompt(1, "first request", 10),
      firstResponse,
      firstCompletion,
      prompt(2, "second request", 40),
    ];

    expect(
      reconcileLiveEventsWithHydratedEvents(
        [
          { ...firstResponse, ts: 21 },
          { ...firstCompletion, ts: 31 },
        ],
        hydratedEvents,
      ),
    ).toEqual([]);
  });

  it("preserves a new assistant response after an overlapping tool boundary", () => {
    const boundary = toolCall("tool-1", 30);
    const nextResponse = agentMessageChunk("after tool", 40);
    const completion = turnComplete(50);
    const hydratedEvents = [
      prompt(1, "run a command", 10),
      agentMessage("before tool", 20),
      boundary,
    ];

    expect(
      reconcileLiveEventsWithHydratedEvents(
        [{ ...boundary, ts: 31 }, nextResponse, completion],
        hydratedEvents,
      ),
    ).toEqual([nextResponse, completion]);
  });

  it("preserves an identical response belonging to the unmatched current prompt", () => {
    const currentResponse = agentMessage("Done", 50);
    const currentCompletion = turnComplete(60);
    const hydratedEvents = [
      prompt(1, "first request", 10),
      agentMessage("Done", 20),
      turnComplete(30),
      prompt(2, "second request", 40),
    ];

    expect(
      reconcileLiveEventsWithHydratedEvents(
        [currentResponse, currentCompletion],
        hydratedEvents,
      ),
    ).toEqual([currentResponse, currentCompletion]);
  });

  it("preserves a repeated response when a partial live tail omits the tool boundary", () => {
    const boundary = toolCall("tool-1", 30);
    const repeatedResponse = agentMessage("Done", 40);
    const completion = turnComplete(50);
    const hydratedEvents = [
      prompt(1, "run a command", 10),
      agentMessage("Done", 20),
      boundary,
    ];

    expect(
      reconcileLiveEventsWithHydratedEvents(
        [repeatedResponse, completion],
        hydratedEvents,
      ),
    ).toEqual([repeatedResponse, completion]);
    expect(
      reconcileLiveEventsWithHydratedEvents(
        [{ ...boundary, ts: 31 }, repeatedResponse, completion],
        hydratedEvents,
      ),
    ).toEqual([repeatedResponse, completion]);
  });

  it("discards a positioned stale tail across a same-millisecond prompt boundary", () => {
    const firstPrompt = prompt(1, "first request", 10);
    const firstResponse = agentMessage("first response", 20);
    const firstCompletion = turnComplete(40);
    const secondPrompt = prompt(2, "second request", 40);
    const hydratedEvents = convertStoredEntriesToEvents(
      [firstPrompt, firstResponse, firstCompletion, secondPrompt].map(
        storedEntry,
      ),
      undefined,
      { taskRunId: "run-1", startEntryIndex: 0 },
    );
    const staleLiveTail = convertStoredEntriesToEvents(
      [firstResponse, firstCompletion].map(storedEntry),
      undefined,
      { taskRunId: "run-1", startEntryIndex: 1 },
    );

    expect(
      reconcileLiveEventsWithHydratedEvents(staleLiveTail, hydratedEvents),
    ).toEqual([]);
  });
});
