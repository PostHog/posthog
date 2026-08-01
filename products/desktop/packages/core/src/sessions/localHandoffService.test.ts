import type { Task } from "@posthog/shared/domain-types";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type LocalHandoffDialog,
  type LocalHandoffHost,
  type LocalHandoffNotifier,
  type LocalHandoffPending,
  LocalHandoffService,
} from "./localHandoffService";
import type { SessionService } from "./sessionService";

function makeDeps() {
  let pending: LocalHandoffPending | null = null;

  const sessionService = {
    preflightToLocal: vi.fn(),
    handoffToLocal: vi.fn().mockResolvedValue(undefined),
  };

  const host: LocalHandoffHost = {
    getRepositoryByRemoteUrl: vi.fn().mockResolvedValue(null),
    selectDirectory: vi.fn().mockResolvedValue(null),
    addFolder: vi.fn().mockResolvedValue(undefined),
  };

  const dialog: LocalHandoffDialog = {
    openConfirm: vi.fn(),
    closeConfirm: vi.fn(),
    cancelPendingFlow: vi.fn(),
    hideDirtyTree: vi.fn(),
    getPendingAfterCommit: vi.fn(() => pending),
    clearPendingAfterCommit: vi.fn(() => {
      pending = null;
    }),
    openDirtyTreeForPendingHandoff: vi.fn(),
  };

  const notifier: LocalHandoffNotifier = {
    error: vi.fn(),
    warn: vi.fn(),
    logError: vi.fn(),
  };

  const service = new LocalHandoffService(
    sessionService as unknown as SessionService,
    host,
    dialog,
    notifier,
  );

  return {
    service,
    sessionService,
    host,
    dialog,
    notifier,
    setPending: (value: LocalHandoffPending | null) => {
      pending = value;
    },
  };
}

describe("LocalHandoffService.continueAfterDirtyTree", () => {
  let deps: ReturnType<typeof makeDeps>;

  beforeEach(() => {
    deps = makeDeps();
  });

  it("hides the dirty tree dialog regardless of branch state", () => {
    deps.service.continueAfterDirtyTree({
      isFeatureBranch: true,
      suggestedBranchName: "fix/thing",
    });
    expect(deps.dialog.hideDirtyTree).toHaveBeenCalledOnce();
  });

  it("routes straight to commit when already on a feature branch", () => {
    const step = deps.service.continueAfterDirtyTree({
      isFeatureBranch: true,
      suggestedBranchName: "fix/thing",
    });
    expect(step).toEqual({ step: "open-commit" });
  });

  it("routes to branch creation with the suggested name otherwise", () => {
    const step = deps.service.continueAfterDirtyTree({
      isFeatureBranch: false,
      suggestedBranchName: "fix/thing",
    });
    expect(step).toEqual({ step: "open-branch", suggestedName: "fix/thing" });
  });
});

describe("LocalHandoffService.afterBranchCreated", () => {
  it("advances to the commit step", () => {
    const { service } = makeDeps();
    expect(service.afterBranchCreated()).toEqual({ step: "open-commit" });
  });
});

describe("LocalHandoffService.afterCommit", () => {
  it("resumes the pending handoff once a commit succeeds", async () => {
    const deps = makeDeps();
    deps.setPending({
      taskId: "task-1",
      repoPath: "/repo",
      branchName: "fix/thing",
    });

    await deps.service.afterCommit();

    expect(deps.dialog.clearPendingAfterCommit).toHaveBeenCalledOnce();
    expect(deps.sessionService.handoffToLocal).toHaveBeenCalledWith(
      "task-1",
      "/repo",
    );
  });

  it("is a no-op when there is no pending handoff", async () => {
    const deps = makeDeps();
    deps.setPending(null);

    await deps.service.afterCommit();

    expect(deps.sessionService.handoffToLocal).not.toHaveBeenCalled();
  });

  it("reports an error when resuming the handoff fails", async () => {
    const deps = makeDeps();
    deps.setPending({
      taskId: "task-1",
      repoPath: "/repo",
      branchName: null,
    });
    deps.sessionService.handoffToLocal.mockRejectedValueOnce(new Error("boom"));

    await deps.service.afterCommit();

    expect(deps.notifier.error).toHaveBeenCalledWith(
      "Failed to continue locally: boom",
    );
  });
});

describe("LocalHandoffService.start", () => {
  const task = { repository: "https://example.com/repo.git" } as Task;

  it("hands off immediately when preflight is clean", async () => {
    const deps = makeDeps();
    deps.host.getRepositoryByRemoteUrl = vi
      .fn()
      .mockResolvedValue({ path: "/repo" });
    deps.sessionService.preflightToLocal.mockResolvedValue({
      canHandoff: true,
    });

    await deps.service.start("task-1", task);

    expect(deps.dialog.closeConfirm).toHaveBeenCalled();
    expect(deps.sessionService.handoffToLocal).toHaveBeenCalledWith(
      "task-1",
      "/repo",
    );
  });

  it("opens the dirty-tree dialog when the local tree is dirty", async () => {
    const deps = makeDeps();
    deps.host.getRepositoryByRemoteUrl = vi
      .fn()
      .mockResolvedValue({ path: "/repo" });
    deps.sessionService.preflightToLocal.mockResolvedValue({
      canHandoff: false,
      localTreeDirty: true,
      changedFiles: [{ path: "a.ts" }],
      localGitState: { branch: "main" },
    });

    await deps.service.start("task-1", task);

    expect(deps.dialog.openDirtyTreeForPendingHandoff).toHaveBeenCalledWith(
      [{ path: "a.ts" }],
      { taskId: "task-1", repoPath: "/repo", branchName: "main" },
    );
  });
});
