import { afterEach, describe, expect, it, vi } from "vitest";
import { formatRelativeTime } from "./format";

const NOW = Date.UTC(2026, 0, 1, 12, 0, 0);
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function at(msAgo: number): number {
  vi.setSystemTime(NOW);
  return NOW - msAgo;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("formatRelativeTime", () => {
  it.each<[string, number, string]>([
    ["the current instant", 0, "just now"],
    ["anything under a minute", 59 * SECOND, "just now"],
    ["exactly a minute", MINUTE, "1m ago"],
    ["minutes", 5 * MINUTE, "5m ago"],
    ["the last minute before an hour", 59 * MINUTE + 59 * SECOND, "59m ago"],
    ["exactly an hour", HOUR, "1h ago"],
    ["hours", 3 * HOUR, "3h ago"],
    ["the last hour before a day", 23 * HOUR + 59 * MINUTE, "23h ago"],
    ["exactly a day", DAY, "1d ago"],
    // Days never roll up into weeks/months/years — the compact form stays
    // readable at any age, which is the whole point of using it everywhere.
    ["days", 3 * DAY, "3d ago"],
    ["very old timestamps", 400 * DAY, "400d ago"],
  ])("formats %s as %s", (_label, msAgo, expected) => {
    vi.useFakeTimers();
    expect(formatRelativeTime(at(msAgo))).toBe(expected);
  });

  it("treats a future timestamp as just now rather than a negative age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    expect(formatRelativeTime(NOW + 5 * MINUTE)).toBe("just now");
  });
});
