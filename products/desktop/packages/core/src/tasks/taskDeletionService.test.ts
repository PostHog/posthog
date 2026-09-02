import type { RootLogger } from "@posthog/di/logger";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ITaskDeletionHost,
  ITaskDeletionWorkspaceClient,
  TaskWorkspace,
} from "./identifiers";
import { TaskDeletionService } from "./taskDeletionService";

function makeDeps(overrides?: {
  workspaces?: Record<string, TaskWorkspace>;
  focusSession?: { worktreePath?: string | null } | null;
  confirmed?: boolean;
  view?: { type: string; data?: { id?: string } | null };
}) {
  const workspace: ITaskDeletionWorkspaceClient = {
    getAll: vi.fn().mockResolvedValue(overrides?.workspaces ?? {}),
    delete: vi.fn().mockResolvedValue(undefined),
  };
  const host: ITaskDeletionHost = {
    getSession: vi.fn().mockReturnValue(overrides?.focusSession ?? null),
    disableFocus: vi.fn().mockResolvedValue(undefined),
    confirmDeleteTask: vi
      .fn()
      .mockResolvedValue({ confirmed: overrides?.confirmed ?? true }),
    unpin: vi.fn().mockResolvedValue(undefined),
    getCurrentView: vi
      .fn()
      .mockReturnValue(overrides?.view ?? { type: "inbox" }),
    navigateToTaskInput: vi.fn(),
  };
  const scoped = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const logger: RootLogger = {
    ...scoped,
    scope: vi.fn(() => scoped),
  };

  return { workspace, host, logger, scoped };
}

function makeService(deps: ReturnType<typeof makeDeps>) {
  return new TaskDeletionService(deps.workspace, deps.host, deps.logger);
}

describe("TaskDeletionService.deleteTask", () => {
  beforeEach(() => vi.clearAllMocks());

  it("deletes the cloud task when no workspace exists", async () => {
    const deps = makeDeps();
    const service = makeService(deps);
    const client = { deleteTask: vi.fn().mockResolvedValue("done") };

    const result = await service.deleteTask(client, "t1");

    expect(result).toBe("done");
    expect(client.deleteTask).toHaveBeenCalledWith("t1");
    expect(deps.workspace.delete).not.toHaveBeenCalled();
    expect(deps.host.disableFocus).not.toHaveBeenCalled();
  });

  it("deletes the worktree before the cloud task when a workspace exists", async () => {
    const deps = makeDeps({
      workspaces: { t1: { worktreePath: "/wt", folderPath: "/repo" } },
    });
    const service = makeService(deps);
    const client = { deleteTask: vi.fn().mockResolvedValue(undefined) };

    await service.deleteTask(client, "t1");

    expect(deps.workspace.delete).toHaveBeenCalledWith({
      taskId: "t1",
      mainRepoPath: "/repo",
    });
    expect(client.deleteTask).toHaveBeenCalledWith("t1");
  });

  it("unfocuses first when the active focus targets this worktree", async () => {
    const deps = makeDeps({
      workspaces: { t1: { worktreePath: "/wt", folderPath: "/repo" } },
      focusSession: { worktreePath: "/wt" },
    });
    const service = makeService(deps);
    const client = { deleteTask: vi.fn().mockResolvedValue(undefined) };

    await service.deleteTask(client, "t1");

    expect(deps.host.disableFocus).toHaveBeenCalledOnce();
  });

  it("does not unfocus when focus targets a different worktree", async () => {
    const deps = makeDeps({
      workspaces: { t1: { worktreePath: "/wt", folderPath: "/repo" } },
      focusSession: { worktreePath: "/other" },
    });
    const service = makeService(deps);
    const client = { deleteTask: vi.fn().mockResolvedValue(undefined) };

    await service.deleteTask(client, "t1");

    expect(deps.host.disableFocus).not.toHaveBeenCalled();
  });

  it("still deletes the cloud task when worktree deletion fails", async () => {
    const deps = makeDeps({
      workspaces: { t1: { worktreePath: "/wt", folderPath: "/repo" } },
    });
    deps.workspace.delete = vi.fn().mockRejectedValue(new Error("boom"));
    const service = makeService(deps);
    const client = { deleteTask: vi.fn().mockResolvedValue("ok") };

    const result = await service.deleteTask(client, "t1");

    expect(result).toBe("ok");
    expect(deps.scoped.error).toHaveBeenCalled();
  });
});

describe("TaskDeletionService.confirmAndDelete", () => {
  beforeEach(() => vi.clearAllMocks());

  it("short-circuits without unpinning or deleting when declined", async () => {
    const deps = makeDeps({ confirmed: false });
    const service = makeService(deps);
    const runDelete = vi.fn();

    const ok = await service.confirmAndDelete(
      { taskId: "t1", taskTitle: "Title", hasWorktree: false },
      runDelete,
    );

    expect(ok).toBe(false);
    expect(deps.host.confirmDeleteTask).toHaveBeenCalledWith({
      taskTitle: "Title",
      hasWorktree: false,
    });
    expect(deps.host.unpin).not.toHaveBeenCalled();
    expect(runDelete).not.toHaveBeenCalled();
  });

  it("unpins and runs the delete when confirmed", async () => {
    const deps = makeDeps({ confirmed: true });
    const service = makeService(deps);
    const runDelete = vi.fn().mockResolvedValue(undefined);

    const ok = await service.confirmAndDelete(
      { taskId: "t1", taskTitle: "Title", hasWorktree: true },
      runDelete,
    );

    expect(ok).toBe(true);
    expect(deps.host.unpin).toHaveBeenCalledWith("t1");
    expect(runDelete).toHaveBeenCalledWith("t1");
  });

  it("navigates away when viewing the deleted task detail", async () => {
    const deps = makeDeps({
      confirmed: true,
      view: { type: "task-detail", data: { id: "t1" } },
    });
    const service = makeService(deps);

    await service.confirmAndDelete(
      { taskId: "t1", taskTitle: "Title", hasWorktree: false },
      vi.fn().mockResolvedValue(undefined),
    );

    expect(deps.host.navigateToTaskInput).toHaveBeenCalledOnce();
  });

  it("does not navigate when viewing a different task", async () => {
    const deps = makeDeps({
      confirmed: true,
      view: { type: "task-detail", data: { id: "other" } },
    });
    const service = makeService(deps);

    await service.confirmAndDelete(
      { taskId: "t1", taskTitle: "Title", hasWorktree: false },
      vi.fn().mockResolvedValue(undefined),
    );

    expect(deps.host.navigateToTaskInput).not.toHaveBeenCalled();
  });
});
