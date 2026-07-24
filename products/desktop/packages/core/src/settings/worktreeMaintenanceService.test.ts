import { describe, expect, it, vi } from "vitest";
import {
  deleteWorktree,
  type WorktreeMaintenanceDeps,
} from "./worktreeMaintenanceService";

function makeDeps(
  overrides: Partial<WorktreeMaintenanceDeps> = {},
): WorktreeMaintenanceDeps {
  return {
    confirmDeleteWorktree: vi.fn().mockResolvedValue({ confirmed: true }),
    deleteWorkspace: vi.fn().mockResolvedValue(undefined),
    deleteWorktree: vi.fn().mockResolvedValue(undefined),
    deleteTask: vi.fn().mockResolvedValue(undefined),
    invalidate: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("deleteWorktree", () => {
  it("aborts when the user cancels confirmation", async () => {
    const deps = makeDeps({
      confirmDeleteWorktree: vi.fn().mockResolvedValue({ confirmed: false }),
    });
    const result = await deleteWorktree(deps, {
      worktreePath: "/wt",
      allTaskIds: ["t1"],
      existingTaskIds: ["t1"],
      folderPath: "/repo",
    });
    expect(result.deleted).toBe(false);
    expect(deps.deleteWorkspace).not.toHaveBeenCalled();
  });

  it("does not confirm when there are no existing tasks", async () => {
    const deps = makeDeps();
    await deleteWorktree(deps, {
      worktreePath: "/wt",
      allTaskIds: [],
      existingTaskIds: [],
      folderPath: "/repo",
    });
    expect(deps.confirmDeleteWorktree).not.toHaveBeenCalled();
    expect(deps.deleteWorktree).toHaveBeenCalledWith({
      worktreePath: "/wt",
      mainRepoPath: "/repo",
    });
  });

  it("deletes per-task workspaces when allTaskIds is non-empty", async () => {
    const deps = makeDeps();
    await deleteWorktree(deps, {
      worktreePath: "/wt",
      allTaskIds: ["t1", "t2"],
      existingTaskIds: ["t1"],
      folderPath: "/repo",
    });
    expect(deps.deleteWorkspace).toHaveBeenCalledTimes(2);
    expect(deps.deleteWorktree).not.toHaveBeenCalled();
    expect(deps.deleteTask).toHaveBeenCalledWith("t1");
    expect(deps.invalidate).toHaveBeenCalledWith("/repo");
  });
});
