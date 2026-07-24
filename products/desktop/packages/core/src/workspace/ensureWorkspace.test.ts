import type { Workspace } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildCreateWorkspaceRequest,
  selectExistingWorkspace,
} from "./ensureWorkspace";

describe("buildCreateWorkspaceRequest", () => {
  it("defaults to worktree mode and undefined branch", () => {
    expect(buildCreateWorkspaceRequest("t1", "/repo")).toEqual({
      taskId: "t1",
      mainRepoPath: "/repo",
      folderId: "",
      folderPath: "/repo",
      mode: "worktree",
      branch: undefined,
    });
  });

  it("normalizes a null branch to undefined", () => {
    expect(
      buildCreateWorkspaceRequest("t1", "/repo", "local", null).branch,
    ).toBe(undefined);
  });

  it("passes through an explicit branch", () => {
    expect(
      buildCreateWorkspaceRequest("t1", "/repo", "worktree", "feat/foo").branch,
    ).toBe("feat/foo");
  });
});

describe("selectExistingWorkspace", () => {
  it("returns the workspace for a task", () => {
    const ws = { taskId: "t1" } as unknown as Workspace;
    expect(selectExistingWorkspace({ t1: ws }, "t1")).toBe(ws);
  });

  it("returns null when absent", () => {
    expect(selectExistingWorkspace({}, "t1")).toBeNull();
  });

  it("returns null when map is undefined", () => {
    expect(selectExistingWorkspace(undefined, "t1")).toBeNull();
  });
});
