import { describe, expect, it } from "vitest";
import {
  computeEffectiveBulkIds,
  computeOrderedVisibleTaskIds,
  computePriorTaskIds,
  computeRangeSelection,
  dedupeTaskIds,
  formatArchiveResult,
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

describe("computeEffectiveBulkIds", () => {
  it("returns empty when nothing selected", () => {
    expect(computeEffectiveBulkIds([], "t1")).toEqual([]);
  });

  it("returns selection unchanged when no active task", () => {
    expect(computeEffectiveBulkIds(["t1", "t2"], null)).toEqual(["t1", "t2"]);
  });

  it("prepends active task when not already selected", () => {
    expect(computeEffectiveBulkIds(["t2"], "t1")).toEqual(["t1", "t2"]);
  });

  it("leaves selection unchanged when active task already selected", () => {
    expect(computeEffectiveBulkIds(["t1", "t2"], "t1")).toEqual(["t1", "t2"]);
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
  it("returns ids created before the clicked task", () => {
    const all = [
      { id: "t1", createdAt: 100 },
      { id: "t2", createdAt: 200 },
      { id: "t3", createdAt: 300 },
    ];
    expect(computePriorTaskIds(all, "t2")).toEqual(["t1"]);
  });

  it("returns empty when clicked task not found", () => {
    expect(computePriorTaskIds([{ id: "t1", createdAt: 1 }], "x")).toEqual([]);
  });
});

describe("formatArchiveResult", () => {
  it("formats success singular", () => {
    expect(formatArchiveResult({ archived: 1, failed: 0 })).toEqual({
      kind: "success",
      message: "1 task archived",
    });
  });

  it("formats success plural", () => {
    expect(formatArchiveResult({ archived: 3, failed: 0 })).toEqual({
      kind: "success",
      message: "3 tasks archived",
    });
  });

  it("formats error with failures", () => {
    expect(formatArchiveResult({ archived: 2, failed: 1 })).toEqual({
      kind: "error",
      message: "2 archived, 1 failed",
    });
  });
});
