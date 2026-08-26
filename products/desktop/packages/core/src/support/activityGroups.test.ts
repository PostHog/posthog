import { describe, expect, it } from "vitest";
import { groupActivity } from "./activityGroups";

function entry(id: string, at: string) {
  return { id, created_at: at };
}

describe("groupActivity", () => {
  it("chains adjacent bursts and keeps distant entries alone", () => {
    const groups = groupActivity([
      entry("a", "2026-08-26T10:00:00Z"),
      entry("b", "2026-08-26T10:00:20Z"),
      entry("c", "2026-08-26T10:00:45Z"),
      entry("d", "2026-08-26T12:00:00Z"),
    ]);
    expect(groups.map((g) => g.entries.map((e) => e.id))).toEqual([
      ["a", "b", "c"],
      ["d"],
    ]);
    expect(groups[0]?.key).toBe("a");
  });

  it("never groups entries with unparseable timestamps", () => {
    const groups = groupActivity([
      entry("a", "2026-08-26T10:00:00Z"),
      entry("b", "not-a-date"),
      entry("c", "2026-08-26T10:00:05Z"),
    ]);
    expect(groups).toHaveLength(3);
  });
});
