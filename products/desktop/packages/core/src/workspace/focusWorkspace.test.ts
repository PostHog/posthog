import type { Workspace } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildEnableFocusParams,
  canFocusWorkspace,
  focusTerminalKey,
} from "./focusWorkspace";

function makeWorkspace(overrides: Partial<Workspace>): Workspace {
  return {
    taskId: "t1",
    folderId: "f1",
    folderPath: "/repo",
    mode: "worktree",
    worktreePath: "/repo/.worktrees/foo",
    worktreeName: "foo",
    branchName: "feat/foo",
    baseBranch: "main",
    linkedBranch: "feat/foo",
    createdAt: "2024-01-01",
    ...overrides,
  };
}

describe("canFocusWorkspace", () => {
  it("is true for a complete worktree workspace", () => {
    expect(canFocusWorkspace(makeWorkspace({}))).toBe(true);
  });

  it("is false for non-worktree mode", () => {
    expect(canFocusWorkspace(makeWorkspace({ mode: "local" }))).toBe(false);
  });

  it("is false without a branch name", () => {
    expect(canFocusWorkspace(makeWorkspace({ branchName: null }))).toBe(false);
  });

  it("is false without a worktree path", () => {
    expect(canFocusWorkspace(makeWorkspace({ worktreePath: null }))).toBe(
      false,
    );
  });

  it("is false for null workspace", () => {
    expect(canFocusWorkspace(null)).toBe(false);
  });
});

describe("focusTerminalKey", () => {
  it("derives the terminal key", () => {
    expect(focusTerminalKey("t1", "feat/foo")).toBe(
      "focus-terminal-t1-feat/foo",
    );
  });
});

describe("buildEnableFocusParams", () => {
  it("builds params from a focusable workspace", () => {
    expect(buildEnableFocusParams(makeWorkspace({}))).toEqual({
      mainRepoPath: "/repo",
      worktreePath: "/repo/.worktrees/foo",
      branch: "feat/foo",
    });
  });

  it("returns null for a non-focusable workspace", () => {
    expect(buildEnableFocusParams(makeWorkspace({ mode: "cloud" }))).toBeNull();
  });
});
