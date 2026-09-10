import { describe, expect, it } from "vitest";
import {
  insertTaskDedup,
  removeTaskFromList,
  shouldNavigateAwayFromDeletedTask,
  shouldUnfocusBeforeDelete,
} from "./taskDelete";

describe("shouldUnfocusBeforeDelete", () => {
  it("returns false when the workspace has no worktree", () => {
    expect(
      shouldUnfocusBeforeDelete({ worktreePath: "/a" }, { worktreePath: null }),
    ).toBe(false);
  });

  it("returns false when no workspace", () => {
    expect(shouldUnfocusBeforeDelete({ worktreePath: "/a" }, null)).toBe(false);
  });

  it("returns true when focus matches the workspace worktree", () => {
    expect(
      shouldUnfocusBeforeDelete({ worktreePath: "/a" }, { worktreePath: "/a" }),
    ).toBe(true);
  });

  it("returns false when focus is on a different worktree", () => {
    expect(
      shouldUnfocusBeforeDelete({ worktreePath: "/b" }, { worktreePath: "/a" }),
    ).toBe(false);
  });

  it("returns false when nothing is focused", () => {
    expect(shouldUnfocusBeforeDelete(null, { worktreePath: "/a" })).toBe(false);
  });
});

describe("removeTaskFromList", () => {
  it("removes the matching task", () => {
    const tasks = [{ id: "a" }, { id: "b" }];
    expect(removeTaskFromList(tasks, "a")).toEqual([{ id: "b" }]);
  });

  it("returns undefined when list is undefined", () => {
    expect(removeTaskFromList(undefined, "a")).toBeUndefined();
  });
});

describe("insertTaskDedup", () => {
  it("prepends a new task", () => {
    const tasks = [{ id: "a" }];
    expect(insertTaskDedup(tasks, { id: "b" })).toEqual([
      { id: "b" },
      { id: "a" },
    ]);
  });

  it("skips inserting a duplicate id", () => {
    const tasks = [{ id: "a" }];
    expect(insertTaskDedup(tasks, { id: "a" })).toBe(tasks);
  });

  it("returns undefined when list is undefined", () => {
    expect(insertTaskDedup(undefined, { id: "a" })).toBeUndefined();
  });
});

describe("shouldNavigateAwayFromDeletedTask", () => {
  it("returns true when viewing the deleted task detail", () => {
    expect(
      shouldNavigateAwayFromDeletedTask(
        { type: "task-detail", data: { id: "a" } },
        "a",
      ),
    ).toBe(true);
  });

  it("returns false for a different detail", () => {
    expect(
      shouldNavigateAwayFromDeletedTask(
        { type: "task-detail", data: { id: "b" } },
        "a",
      ),
    ).toBe(false);
  });

  it("returns false for other views", () => {
    expect(shouldNavigateAwayFromDeletedTask({ type: "inbox" }, "a")).toBe(
      false,
    );
  });
});
