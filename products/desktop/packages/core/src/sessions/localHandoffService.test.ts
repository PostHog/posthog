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
    getWorktreeLocation: vi.fn().mockResolvedValue("/worktrees"),
    cloneRepository: vi.fn().mockResolvedValue(undefined),
    addAdditionalDirectory: vi.fn().mockResolvedValue(undefined),
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
      undefined,
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
      { "https://example.com/repo.git": "/repo" },
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
      {
        taskId: "task-1",
        repoPath: "/repo",
        branchName: "main",
        repositoryPaths: { "https://example.com/repo.git": "/repo" },
      },
    );
  });

  it("reuses local repositories and clones missing ones before handoff", async () => {
    const deps = makeDeps();
    const multiRepoTask = {
      repositories: ["posthog/posthog", "posthog/posthog-js"],
    } as Task;
    deps.host.getRepositoryByRemoteUrl = vi
      .fn()
      .mockResolvedValueOnce({ path: "/repos/posthog" })
      .mockResolvedValueOnce(null);
    deps.sessionService.preflightToLocal.mockResolvedValue({
      canHandoff: true,
    });

    await deps.service.start("task-1", multiRepoTask);

    expect(deps.host.cloneRepository).toHaveBeenCalledWith(
      expect.objectContaining({
        repoUrl: "https://github.com/posthog/posthog-js.git",
        targetPath: "/worktrees/linked-repositories/posthog/posthog-js",
      }),
    );
    expect(deps.host.addAdditionalDirectory).toHaveBeenCalledWith({
      taskId: "task-1",
      path: "/worktrees/linked-repositories/posthog/posthog-js",
    });
    expect(deps.sessionService.handoffToLocal).toHaveBeenCalledWith(
      "task-1",
      "/repos/posthog",
      {
        "posthog/posthog": "/repos/posthog",
        "posthog/posthog-js":
          "/worktrees/linked-repositories/posthog/posthog-js",
      },
    );
  });

  // A task's repositories are team-writable via the API, so an unsafe entry must
  // never reach `git clone` (RCE via git's remote-ext transport) or escape the
  // clone root through path traversal. The safe repo alongside it still clones.
  it.each([
    ["remote-ext RCE", "ext::sh -c 'touch pwned'/repo"],
    ["path traversal", "../evil"],
    ["absolute-ish scheme", "file:///etc/passwd/repo"],
    ["trailing whitespace alias", "posthog/posthog-js "],
    ["extra path segment", "posthog/posthog-js/../../evil"],
  ])("rejects an unsafe repository entry (%s)", async (_label, malicious) => {
    const deps = makeDeps();
    deps.host.getRepositoryByRemoteUrl = vi.fn().mockResolvedValue(null);
    deps.sessionService.preflightToLocal.mockResolvedValue({
      canHandoff: true,
    });

    await deps.service.start("task-1", {
      repositories: ["posthog/posthog", malicious],
    } as Task);

    // Only the safe repo is cloned, and always through an explicit https URL.
    expect(deps.host.cloneRepository).toHaveBeenCalledTimes(1);
    expect(deps.host.cloneRepository).toHaveBeenCalledWith(
      expect.objectContaining({
        repoUrl: "https://github.com/posthog/posthog.git",
      }),
    );
    expect(deps.notifier.warn).toHaveBeenCalledWith(
      expect.stringContaining(malicious),
    );
    const [, , repositoryPaths] =
      deps.sessionService.handoffToLocal.mock.calls[0];
    expect(repositoryPaths).toEqual({
      "posthog/posthog": "/worktrees/linked-repositories/posthog/posthog",
    });
  });

  it("de-duplicates case-variant repository aliases before cloning", async () => {
    const deps = makeDeps();
    deps.host.getRepositoryByRemoteUrl = vi.fn().mockResolvedValue(null);
    deps.sessionService.preflightToLocal.mockResolvedValue({
      canHandoff: true,
    });

    await deps.service.start("task-1", {
      repositories: ["PostHog/PostHog", "posthog/posthog"],
    } as Task);

    // Both collapse to one target, so the racing double-clone can't happen.
    expect(deps.host.cloneRepository).toHaveBeenCalledTimes(1);
    const [, , repositoryPaths] =
      deps.sessionService.handoffToLocal.mock.calls[0];
    expect(repositoryPaths).toEqual({
      "posthog/posthog": "/worktrees/linked-repositories/posthog/posthog",
    });
  });
});
