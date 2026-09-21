import { describe, expect, it } from "vitest";
import { type FeedEntry, keepFilteredEntries } from "./channelFeedDisplay";

function task(id: string): FeedEntry {
  return {
    kind: "task",
    id,
    createdAt: "2026-09-18T10:00:00Z",
    task: { id },
  } as unknown as FeedEntry;
}

function report(id: string): FeedEntry {
  return {
    kind: "report",
    id,
    createdAt: "2026-09-18T10:00:00Z",
    report: { id, title: "A report" },
  } as unknown as FeedEntry;
}

describe("keepFilteredEntries", () => {
  it("returns every entry when no filter is applied", () => {
    const entries = [task("a"), report("r")];
    expect(keepFilteredEntries(entries, null)).toBe(entries);
  });

  it("keeps a report that no filter can speak for", () => {
    const kept = keepFilteredEntries(
      [task("a"), task("b"), report("r")],
      new Set(["task:a"]),
    );
    expect(kept.map((entry) => entry.kind)).toEqual(["task", "report"]);
  });

  it("drops a session the filter excludes", () => {
    const kept = keepFilteredEntries(
      [task("a"), task("b")],
      new Set(["task:b"]),
    );
    expect(kept).toHaveLength(1);
    expect(kept[0]).toMatchObject({ kind: "task", id: "b" });
  });
});
