import { describe, expect, it } from "vitest";
import {
  limitTasksPerGroup,
  readRunMode,
  sliceVisibleTasks,
} from "./buildSidebarData";
import type { TaskData, TaskGroup } from "./sidebarData.types";

function makeTask(id: string): TaskData {
  return {
    id,
    title: `Task ${id}`,
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
  };
}

function makeGroup(id: string, taskCount: number): TaskGroup {
  return {
    id,
    name: id,
    tasks: Array.from({ length: taskCount }, (_, i) => makeTask(`${id}-${i}`)),
  };
}

describe("sliceVisibleTasks", () => {
  it("caps the flat list to the visible count and reports hasMore", () => {
    const tasks = Array.from({ length: 30 }, (_, i) => makeTask(String(i)));
    const { flatTasks, hasMore } = sliceVisibleTasks(tasks, 25);
    expect(flatTasks).toHaveLength(25);
    expect(flatTasks[0]?.id).toBe("0");
    expect(hasMore).toBe(true);
  });

  it("returns every task and hasMore=false when under the cap", () => {
    const tasks = Array.from({ length: 10 }, (_, i) => makeTask(String(i)));
    const { flatTasks, hasMore } = sliceVisibleTasks(tasks, 25);
    expect(flatTasks).toHaveLength(10);
    expect(hasMore).toBe(false);
  });

  it("reports hasMore=false when the count exactly matches the cap", () => {
    const tasks = Array.from({ length: 25 }, (_, i) => makeTask(String(i)));
    expect(sliceVisibleTasks(tasks, 25).hasMore).toBe(false);
  });
});

describe("limitTasksPerGroup", () => {
  it("caps each group independently so quiet groups still show tasks", () => {
    const groups = [makeGroup("busy", 40), makeGroup("quiet", 3)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]?.tasks).toHaveLength(25);
    expect(limited[1]?.tasks).toHaveLength(3);
    expect(hasMore).toBe(true);
  });

  it("keeps empty groups (e.g. registered folders with no tasks)", () => {
    const groups = [makeGroup("empty", 0)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]?.tasks).toHaveLength(0);
    expect(hasMore).toBe(false);
  });

  it("does not clone groups that are under the cap", () => {
    const groups = [makeGroup("small", 5)];
    const { groups: limited, hasMore } = limitTasksPerGroup(groups, 25);
    expect(limited[0]).toBe(groups[0]);
    expect(hasMore).toBe(false);
  });
});

// The mode decides whether a run's `in_progress` is a claim that work is
// happening. Defaulting the wrong way marks every finished interactive session
// as pending, which is what this replaced.
describe("readRunMode", () => {
  it.each([
    ["an interactive run", { mode: "interactive" }, "interactive"],
    ["a background run", { mode: "background" }, "background"],
    // The backend's own default for a run whose state never carried a mode.
    ["a run with no mode", {}, "background"],
    ["a run with no state at all", undefined, "background"],
    ["a mode that is not a mode", { mode: 7 }, "background"],
  ])("reads %s", (_case, state, expected) => {
    expect(readRunMode(state)).toBe(expected);
  });
});
