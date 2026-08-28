import { describe, expect, it } from "vitest";
import {
  computeBulkPinDirection,
  computeOrderedVisibleTaskIds,
  computePriorTaskIds,
  computeRangeSelection,
  dedupeTaskIds,
  formatArchiveResult,
  formatBulkArchiveWarning,
  formatBulkResult,
  pruneToVisible,
} from "./selection";
import type { TaskData } from "./sidebarData.types";

function makeTaskData(id: string, overrides: Partial<TaskData> = {}): TaskData {
  return {
    id,
    title: id,
    createdAt: 0,
    lastActivityAt: 0,
    isGenerating: false,
    isUnread: false,
    isPinned: false,
    needsPermission: false,
    repository: null,
    isSuspended: false,
    folderPath: null,
    cloudPrUrl: null,
    branchName: null,
    linkedBranch: null,
    ...overrides,
  };
}

describe("computeRangeSelection", () => {
  const orderedIds = ["t1", "t2", "t3", "t4", "t5"];

  it.each([
    { direction: "forward", anchor: "t2", target: "t4" },
    { direction: "backward", anchor: "t4", target: "t2" },
  ])("selects a $direction range", ({ anchor, target }) => {
    const result = computeRangeSelection(anchor, target, orderedIds, []);
    expect(result.selectedTaskIds).toEqual(["t2", "t3", "t4"]);
  });

  it("merges range with existing selection", () => {
    const result = computeRangeSelection("t3", "t5", orderedIds, ["t1"]);
    expect(result.selectedTaskIds).toEqual(["t1", "t3", "t4", "t5"]);
  });

  it.each([
    { name: "no anchor", anchor: null },
    { name: "anchor not in list", anchor: "t99" },
  ])("selects just the target when $name", ({ anchor }) => {
    const result = computeRangeSelection(anchor, "t3", orderedIds, []);
    expect(result.selectedTaskIds).toEqual(["t3"]);
  });

  it("updates lastClickedId to the target", () => {
    const result = computeRangeSelection("t1", "t3", orderedIds, []);
    expect(result.lastClickedId).toBe("t3");
  });
});

describe("dedupeTaskIds", () => {
  it("removes duplicates preserving order", () => {
    expect(dedupeTaskIds(["t1", "t2", "t1", "t3", "t2"])).toEqual([
      "t1",
      "t2",
      "t3",
    ]);
  });
});

describe("pruneToVisible", () => {
  it("keeps only visible ids", () => {
    expect(pruneToVisible(["t1", "t2", "t3"], ["t2", "t4"])).toEqual(["t2"]);
  });
});

describe("computeOrderedVisibleTaskIds", () => {
  it("uses flat order in chronological mode", () => {
    const ids = computeOrderedVisibleTaskIds(
      {
        pinnedTasks: [makeTaskData("p1")],
        flatTasks: [makeTaskData("t1"), makeTaskData("t2")],
        groupedTasks: [],
      },
      "chronological",
      new Set(),
    );
    expect(ids).toEqual(["p1", "t1", "t2"]);
  });

  it("skips collapsed groups in by-project mode", () => {
    const ids = computeOrderedVisibleTaskIds(
      {
        pinnedTasks: [],
        flatTasks: [],
        groupedTasks: [
          { id: "g1", name: "g1", tasks: [makeTaskData("a")] },
          { id: "g2", name: "g2", tasks: [makeTaskData("b")] },
        ],
      },
      "by-project",
      new Set(["g2"]),
    );
    expect(ids).toEqual(["a"]);
  });
});

describe("computePriorTaskIds", () => {
  it("returns ids last active before the clicked task", () => {
    const all = [
      { id: "t1", lastActivityAt: 100 },
      { id: "t2", lastActivityAt: 200 },
      { id: "t3", lastActivityAt: 300 },
    ];
    expect(computePriorTaskIds(all, "t2")).toEqual(["t1"]);
  });

  it("returns empty when clicked task not found", () => {
    expect(computePriorTaskIds([{ id: "t1", lastActivityAt: 1 }], "x")).toEqual(
      [],
    );
  });
});

describe("computeBulkPinDirection", () => {
  it.each([
    { name: "nothing selected", selected: [], pinned: [], expected: "pin" },
    {
      name: "none pinned",
      selected: ["t1", "t2"],
      pinned: [],
      expected: "pin",
    },
    {
      name: "some pinned",
      selected: ["t1", "t2"],
      pinned: ["t1"],
      expected: "pin",
    },
    {
      name: "all pinned",
      selected: ["t1", "t2"],
      pinned: ["t1", "t2", "t3"],
      expected: "unpin",
    },
  ])("returns $expected when $name", ({ selected, pinned, expected }) => {
    expect(computeBulkPinDirection(selected, new Set(pinned))).toBe(expected);
  });
});

describe("formatBulkResult", () => {
  it.each([
    { kind: "archived" as const, succeeded: 1, message: "1 session archived" },
    { kind: "archived" as const, succeeded: 3, message: "3 sessions archived" },
    { kind: "pinned" as const, succeeded: 4, message: "4 sessions pinned" },
    { kind: "unpinned" as const, succeeded: 2, message: "2 sessions unpinned" },
    { kind: "filed" as const, succeeded: 1, message: "1 session filed" },
    {
      kind: "added to Command Center" as const,
      succeeded: 2,
      message: "2 sessions added to Command Center",
    },
  ])("formats $succeeded $kind", ({ kind, succeeded, message }) => {
    expect(formatBulkResult(kind, { succeeded, failed: 0 })).toEqual({
      kind: "success",
      message,
    });
  });

  it("reports failures as an error", () => {
    expect(formatBulkResult("pinned", { succeeded: 2, failed: 1 })).toEqual({
      kind: "error",
      message: "2 pinned, 1 failed",
    });
  });
});

describe("formatBulkArchiveWarning", () => {
  it.each([
    {
      name: "nothing running",
      counts: { running: 0, stopsCloudSandbox: false },
      expected: "You can unarchive them later.",
    },
    {
      name: "one running",
      counts: { running: 1, stopsCloudSandbox: false },
      expected:
        "You can unarchive them later. 1 of them is still running and will be stopped.",
    },
    {
      name: "several running",
      counts: { running: 3, stopsCloudSandbox: false },
      expected:
        "You can unarchive them later. 3 of them are still running and will be stopped.",
    },
    {
      name: "a cloud sandbox",
      counts: { running: 2, stopsCloudSandbox: true },
      expected:
        "You can unarchive them later. 2 of them are still running and will be stopped. Any cloud sandbox in the selection shuts down too.",
    },
  ])("describes $name", ({ counts, expected }) => {
    expect(formatBulkArchiveWarning(counts)).toBe(expected);
  });
});

describe("formatArchiveResult", () => {
  it("formats success", () => {
    expect(formatArchiveResult({ archived: 3, failed: 0 })).toEqual({
      kind: "success",
      message: "3 sessions archived",
    });
  });

  it("formats error with failures", () => {
    expect(formatArchiveResult({ archived: 2, failed: 1 })).toEqual({
      kind: "error",
      message: "2 archived, 1 failed",
    });
  });
});
