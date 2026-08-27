import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  convertStoredEntriesToPortableSessionEvents,
  inferStoredLogEntryDirection,
} from "./portableSessionEvents";

describe("inferStoredLogEntryDirection", () => {
  it.each([
    [
      "client requests",
      { notification: { id: 1, method: "session/prompt" } },
      "client",
    ],
    ["agent responses", { notification: { id: 1, result: {} } }, "agent"],
    [
      "agent notifications",
      { notification: { method: "session/update" } },
      "agent",
    ],
    ["missing messages", {}, "agent"],
  ] as const)("classifies %s", (_name, entry, expected) => {
    expect(inferStoredLogEntryDirection(entry as StoredLogEntry)).toBe(
      expected,
    );
  });
});

describe("convertStoredEntriesToPortableSessionEvents", () => {
  it("projects session updates alongside their raw ACP message", () => {
    const notification = {
      update: {
        sessionUpdate: "user_message_chunk",
        content: { type: "text", text: "hello" },
      },
    };
    const events = convertStoredEntriesToPortableSessionEvents([
      {
        type: "notification",
        timestamp: "2026-07-21T12:00:00.000Z",
        notification: { method: "session/update", params: notification },
      },
    ]);

    expect(events).toEqual([
      {
        type: "acp_message",
        direction: "agent",
        ts: 1_784_635_200_000,
        message: { method: "session/update", params: notification },
      },
      {
        type: "session_update",
        ts: 1_784_635_200_000,
        notification,
      },
    ]);
  });

  it("uses the current time when an entry has no timestamp", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-21T12:00:00.000Z"));

    const events = convertStoredEntriesToPortableSessionEvents([
      { type: "response", notification: { id: 1, result: {} } },
    ]);

    expect(events[0]?.ts).toBe(1_784_635_200_000);
    vi.useRealTimers();
  });
});
