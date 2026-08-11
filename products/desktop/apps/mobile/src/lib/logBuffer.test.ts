import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  appendLogEntry,
  clearLogEntries,
  formatLogEntries,
  getLogEntries,
  subscribeToLogEntries,
} from "./logBuffer";

beforeEach(() => {
  clearLogEntries();
});

describe("logBuffer", () => {
  it("captures entries with serialized details", () => {
    appendLogEntry("warn", "tasks", "fetch failed", [
      new Error("boom"),
      { status: 500 },
    ]);

    const [entry] = getLogEntries();
    expect(entry.level).toBe("warn");
    expect(entry.scope).toBe("tasks");
    expect(entry.message).toBe("fetch failed");
    expect(entry.details).toBe('Error: boom {"status":500}');
  });

  it("caps the buffer at 500 entries, dropping the oldest", () => {
    for (let i = 0; i < 510; i++) {
      appendLogEntry("info", "s", `m${i}`, []);
    }

    const entries = getLogEntries();
    expect(entries).toHaveLength(500);
    expect(entries[0].message).toBe("m10");
    expect(entries.at(-1)?.message).toBe("m509");
  });

  it("notifies subscribers on append and clear until unsubscribed", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToLogEntries(listener);

    appendLogEntry("info", "s", "m", []);
    clearLogEntries();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    appendLogEntry("info", "s", "m2", []);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("never throws on unserializable details", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;

    appendLogEntry("debug", "s", "m", [circular]);

    expect(getLogEntries()[0].details).toBe("[object Object]");
  });

  it("formats entries as one line each", () => {
    appendLogEntry("error", "auth", "token refresh failed", ["401"]);

    const text = formatLogEntries(getLogEntries());
    expect(text).toMatch(
      /^\d{4}-\d{2}-\d{2}T.*ERROR \[auth\] token refresh failed 401$/,
    );
  });
});
