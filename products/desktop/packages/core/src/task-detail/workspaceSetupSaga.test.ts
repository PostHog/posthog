import type { RootLogger } from "@posthog/di/logger";
import type { Workspace } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  type WorkspaceSetupExecutor,
  WorkspaceSetupSaga,
} from "./workspaceSetupSaga";

function makeLogger(): RootLogger {
  const scoped = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: () => scoped };
}

function makeExecutor(
  overrides: Partial<WorkspaceSetupExecutor> = {},
): WorkspaceSetupExecutor {
  return {
    addFolder: vi.fn().mockResolvedValue(undefined),
    ensureWorkspace: vi.fn().mockResolvedValue({} as Workspace),
    ...overrides,
  };
}

describe("WorkspaceSetupSaga.setupWorkspace", () => {
  it("adds the folder then ensures the workspace in order", async () => {
    const calls: string[] = [];
    const executor = makeExecutor({
      addFolder: vi.fn(async () => {
        calls.push("addFolder");
      }),
      ensureWorkspace: vi.fn(async () => {
        calls.push("ensureWorkspace");
        return {} as Workspace;
      }),
    });
    const saga = new WorkspaceSetupSaga(makeLogger());

    const result = await saga.setupWorkspace(executor, "task-1", "/repo");

    expect(result).toEqual({ success: true });
    expect(calls).toEqual(["addFolder", "ensureWorkspace"]);
    expect(executor.ensureWorkspace).toHaveBeenCalledWith(
      "task-1",
      "/repo",
      "worktree",
    );
  });

  it("returns a failure when addFolder throws", async () => {
    const executor = makeExecutor({
      addFolder: vi.fn().mockRejectedValue(new Error("boom")),
    });
    const saga = new WorkspaceSetupSaga(makeLogger());

    const result = await saga.setupWorkspace(executor, "task-1", "/repo");

    expect(result).toEqual({
      success: false,
      error: "boom",
    });
    expect(executor.ensureWorkspace).not.toHaveBeenCalled();
  });

  it("returns a failure when ensureWorkspace throws", async () => {
    const executor = makeExecutor({
      ensureWorkspace: vi.fn().mockRejectedValue(new Error("boom")),
    });
    const saga = new WorkspaceSetupSaga(makeLogger());

    const result = await saga.setupWorkspace(executor, "task-1", "/repo");

    expect(result.success).toBe(false);
  });
});
