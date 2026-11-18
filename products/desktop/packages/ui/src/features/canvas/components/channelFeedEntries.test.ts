import { describe, expect, it } from "vitest";
import {
  type FeedEntry,
  feedEntryMatchesTypes,
  keepFilteredEntries,
  mergeFeedEntries,
} from "./channelFeedDisplay";

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

describe("mergeFeedEntries", () => {
  it("dates a pull request by the session that opened it", () => {
    const older = {
      id: "t1",
      title: "Older",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T12:00:00Z",
    };
    const newer = {
      id: "t2",
      title: "Newer",
      created_at: "2026-09-18T10:00:00Z",
      updated_at: "2026-09-18T12:00:00Z",
    };
    const merged = mergeFeedEntries(
      [older, newer] as never,
      [],
      [],
      [],
      [
        { url: "https://github.com/a/b/pull/1", task: older } as never,
        { url: "https://github.com/a/b/pull/2", task: newer } as never,
      ],
    );
    expect(merged.map((entry) => entry.id)).toEqual([
      "pr:https://github.com/a/b/pull/2",
      "t2",
      "pr:https://github.com/a/b/pull/1",
      "t1",
    ]);
  });
});

describe("feedEntryMatchesTypes", () => {
  it("keeps a system row with the sessions it reports on", () => {
    const system = { kind: "system" } as unknown as FeedEntry;
    expect(feedEntryMatchesTypes(system, ["task"])).toBe(true);
    expect(feedEntryMatchesTypes(system, ["canvas", "pr"])).toBe(false);
  });

  it("drops a kind its segment turned off", () => {
    expect(feedEntryMatchesTypes(report("r"), ["task", "pr"])).toBe(false);
    expect(feedEntryMatchesTypes(report("r"), ["report"])).toBe(true);
  });
});
