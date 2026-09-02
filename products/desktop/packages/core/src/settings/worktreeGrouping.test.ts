import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildTaskMap,
  groupWorktrees,
  parseWorktreeLimit,
} from "./worktreeGrouping";

const entry = (path: string) => ({
  worktreePath: path,
  head: "abc",
  branch: "main",
  taskIds: [],
});

describe("groupWorktrees", () => {
  it("skips folders with no worktrees and sorts by folder path", () => {
    const groups = groupWorktrees(
      [{ path: "/b" }, { path: "/a" }, { path: "/c" }],
      [[entry("/b/wt")], undefined, [entry("/c/wt")]],
    );
    expect(groups.map((g) => g.folderPath)).toEqual(["/b", "/c"]);
  });

  it("skips folders with an empty worktree list", () => {
    const groups = groupWorktrees([{ path: "/a" }], [[]]);
    expect(groups).toEqual([]);
  });
});

describe("buildTaskMap", () => {
  it("indexes tasks by id", () => {
    const tasks = [{ id: "t1" }, { id: "t2" }] as unknown as Task[];
    const map = buildTaskMap(tasks);
    expect(map.get("t1")).toBe(tasks[0]);
    expect(map.size).toBe(2);
  });

  it("returns an empty map when undefined", () => {
    expect(buildTaskMap(undefined).size).toBe(0);
  });
});

describe("parseWorktreeLimit", () => {
  it("returns the parsed value when >= 1", () => {
    expect(parseWorktreeLimit("5")).toBe(5);
  });

  it("returns null for values below 1", () => {
    expect(parseWorktreeLimit("0")).toBeNull();
    expect(parseWorktreeLimit("abc")).toBeNull();
  });
});
