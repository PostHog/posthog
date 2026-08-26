import type { Workspace } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { resolveLocalRepoPath } from "./localRepoPath";

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

describe("resolveLocalRepoPath", () => {
  it("returns undefined without a workspace", () => {
    expect(resolveLocalRepoPath(null, false)).toBeUndefined();
  });

  it("targets the main repo when focused", () => {
    expect(resolveLocalRepoPath(makeWorkspace({}), true)).toBe("/repo");
  });

  it("targets the worktree when not focused", () => {
    expect(resolveLocalRepoPath(makeWorkspace({}), false)).toBe(
      "/repo/.worktrees/foo",
    );
  });

  it("falls back to folder path when worktree path is null", () => {
    expect(
      resolveLocalRepoPath(makeWorkspace({ worktreePath: null }), false),
    ).toBe("/repo");
  });
});
