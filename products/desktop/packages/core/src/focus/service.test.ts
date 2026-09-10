import type {
  FocusResult,
  FocusSession,
  StashResult,
} from "@posthog/workspace-client/types";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type EnableFocusParams,
  FocusController,
  type FocusControllerDeps,
} from "./service";

const MAIN_REPO = "/repo/main";
const WORKTREE = "/repo/worktrees/feature";
const OTHER_WORKTREE = "/repo/worktrees/other";

const ok: FocusResult = { success: true };

function createSession(overrides: Partial<FocusSession> = {}): FocusSession {
  return {
    mainRepoPath: MAIN_REPO,
    worktreePath: WORKTREE,
    branch: "feature",
    originalBranch: "main",
    mainStashRef: null,
    commitSha: "sha-main",
    ...overrides,
  };
}

function createParams(
  overrides: Partial<EnableFocusParams> = {},
): EnableFocusParams {
  return {
    mainRepoPath: MAIN_REPO,
    worktreePath: WORKTREE,
    branch: "feature",
    ...overrides,
  };
}

type Deps = {
  [K in keyof FocusControllerDeps]: ReturnType<typeof vi.fn>;
} & FocusControllerDeps;

function createDeps(overrides: Partial<FocusControllerDeps> = {}): Deps {
  const stashResult: StashResult = { success: true, stashRef: "stash@{0}" };
  const deps: FocusControllerDeps = {
    cancelSessionPrompt: vi.fn(async () => {}),
    checkout: vi.fn(async () => ok),
    cleanWorkingTree: vi.fn(async () => {}),
    deleteSession: vi.fn(async () => {}),
    detachWorktree: vi.fn(async () => ok),
    getCommitSha: vi.fn(async () => "sha-main"),
    getCurrentBranch: vi.fn(async () => "main"),
    getSession: vi.fn(async () => null),
    isDirty: vi.fn(async () => false),
    listLocalTaskIds: vi.fn(async () => []),
    listSessionIds: vi.fn(async () => []),
    listWorktreeTaskIds: vi.fn(async () => []),
    notifySessionContext: vi.fn(async () => {}),
    reattachWorktree: vi.fn(async () => ok),
    saveSession: vi.fn(async () => {}),
    stash: vi.fn(async () => stashResult),
    stashApply: vi.fn(async () => ok),
    startSync: vi.fn(async () => {}),
    startWatchingMainRepo: vi.fn(async () => {}),
    stopSync: vi.fn(async () => {}),
    stopWatchingMainRepo: vi.fn(async () => {}),
    toRelativeWorktreePath: vi.fn(async (absolutePath: string) => absolutePath),
    worktreeExistsAtPath: vi.fn(async () => true),
    ...overrides,
  };
  return deps as Deps;
}

describe("FocusController.enableFocus", () => {
  let deps: Deps;
  let controller: FocusController;

  beforeEach(() => {
    deps = createDeps();
    controller = new FocusController(deps);
  });

  it("focuses a clean repo without stashing", async () => {
    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(true);
    expect(deps.stash).not.toHaveBeenCalled();
    expect(result.session?.mainStashRef).toBeNull();
  });

  it("runs the host steps in dependency order on the happy path", async () => {
    await controller.enableFocus(createParams(), null);

    expect(deps.detachWorktree).toHaveBeenCalledWith(WORKTREE);
    expect(deps.checkout).toHaveBeenCalledWith(MAIN_REPO, "feature");
    expect(deps.startSync).toHaveBeenCalledWith(MAIN_REPO, WORKTREE);
    expect(deps.startWatchingMainRepo).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("persists a session derived from the current branch and commit", async () => {
    deps.getCurrentBranch.mockResolvedValue("main");
    deps.getCommitSha.mockResolvedValue("sha-xyz");

    const result = await controller.enableFocus(createParams(), null);

    expect(result.session).toEqual({
      mainRepoPath: MAIN_REPO,
      worktreePath: WORKTREE,
      branch: "feature",
      originalBranch: "main",
      mainStashRef: null,
      commitSha: "sha-xyz",
    });
    expect(deps.saveSession).toHaveBeenCalledWith(result.session);
  });

  it("stashes dirty changes and records the stash ref on the session", async () => {
    deps.isDirty.mockResolvedValue(true);

    const result = await controller.enableFocus(createParams(), null);

    expect(deps.stash).toHaveBeenCalledTimes(1);
    expect(result.session?.mainStashRef).toBe("stash@{0}");
  });

  it("returns the existing session without re-running when already focused", async () => {
    const current = createSession();

    const result = await controller.enableFocus(createParams(), current);

    expect(result).toEqual({ success: true, session: current, wasSwap: false });
    expect(deps.detachWorktree).not.toHaveBeenCalled();
  });

  it("swaps focus by unfocusing the current session first", async () => {
    const current = createSession({ worktreePath: OTHER_WORKTREE });

    const result = await controller.enableFocus(createParams(), current);

    expect(result.success).toBe(true);
    expect(result.wasSwap).toBe(true);
    // unfocus reattaches the previously focused worktree before the new focus.
    expect(deps.reattachWorktree).toHaveBeenCalledWith(
      OTHER_WORKTREE,
      "feature",
    );
  });

  it("fails when the main repo is in detached HEAD state", async () => {
    deps.getCurrentBranch.mockResolvedValue(null);

    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(false);
    expect(result.error).toMatch(/detached HEAD/i);
    expect(deps.detachWorktree).not.toHaveBeenCalled();
  });

  it("fails when already on the target branch", async () => {
    deps.getCurrentBranch.mockResolvedValue("feature");

    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(false);
    expect(result.error).toMatch(/already on branch "feature"/);
  });

  it("translates a checkout-overwrite failure into an actionable message", async () => {
    deps.checkout.mockResolvedValue({
      success: false,
      error: "error: Your local changes would be overwritten by checkout",
    });

    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(false);
    expect(result.error).toMatch(/uncommitted changes would be overwritten/);
  });

  it("rolls back stash and worktree detach when checkout fails", async () => {
    deps.isDirty.mockResolvedValue(true);
    deps.checkout.mockResolvedValue({ success: false, error: "boom" });

    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(false);
    // detach_worktree rollback reattaches; stash_dirty_changes rollback re-applies.
    expect(deps.reattachWorktree).toHaveBeenCalledWith(WORKTREE, "feature");
    expect(deps.stashApply).toHaveBeenCalledWith(MAIN_REPO, "stash@{0}");
  });

  it("fails and does not detach when stashing dirty changes fails", async () => {
    deps.isDirty.mockResolvedValue(true);
    deps.stash.mockResolvedValue({ success: false, error: "stash failed" });

    const result = await controller.enableFocus(createParams(), null);

    expect(result.success).toBe(false);
    expect(deps.detachWorktree).not.toHaveBeenCalled();
  });
});

describe("FocusController.disableFocus", () => {
  let deps: Deps;
  let controller: FocusController;

  beforeEach(() => {
    deps = createDeps();
    controller = new FocusController(deps);
  });

  it("restores the original branch and reattaches the worktree", async () => {
    const result = await controller.disableFocus(createSession());

    expect(result.success).toBe(true);
    expect(deps.checkout).toHaveBeenCalledWith(MAIN_REPO, "main");
    expect(deps.reattachWorktree).toHaveBeenCalledWith(WORKTREE, "feature");
    expect(deps.deleteSession).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("does not warn when there was no stash to restore", async () => {
    const result = await controller.disableFocus(createSession());

    expect(result).toEqual({ success: true, stashPopWarning: undefined });
    expect(deps.stashApply).not.toHaveBeenCalled();
  });

  it("re-applies a recorded stash on disable", async () => {
    const result = await controller.disableFocus(
      createSession({ mainStashRef: "stash@{2}" }),
    );

    expect(deps.stashApply).toHaveBeenCalledWith(MAIN_REPO, "stash@{2}");
    expect(result.success && result.stashPopWarning).toBeUndefined();
  });

  it("surfaces a recoverable warning when stash apply fails", async () => {
    deps.stashApply.mockResolvedValue({ success: false, error: "conflict" });

    const result = await controller.disableFocus(
      createSession({ mainStashRef: "stash@{2}" }),
    );

    expect(result.success).toBe(true);
    expect(result.success && result.stashPopWarning).toMatch(/stash@\{2\}/);
  });

  it("fails and rolls back when reattaching the worktree fails", async () => {
    deps.reattachWorktree.mockResolvedValue({
      success: false,
      error: "locked",
    });

    const result = await controller.disableFocus(createSession());

    expect(result.success).toBe(false);
    // checkout_original_branch rollback restores the focused branch.
    expect(deps.checkout).toHaveBeenCalledWith(MAIN_REPO, "feature");
  });
});

describe("FocusController.restore", () => {
  let deps: Deps;
  let controller: FocusController;

  beforeEach(() => {
    deps = createDeps();
    controller = new FocusController(deps);
  });

  it("returns null when there is no persisted session", async () => {
    deps.getSession.mockResolvedValue(null);

    expect(await controller.restore(MAIN_REPO)).toBeNull();
    expect(deps.startWatchingMainRepo).not.toHaveBeenCalled();
  });

  it("discards a session whose original branch equals its focused branch", async () => {
    deps.getSession.mockResolvedValue(
      createSession({ branch: "main", originalBranch: "main" }),
    );

    expect(await controller.restore(MAIN_REPO)).toBeNull();
    expect(deps.deleteSession).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("discards a session whose worktree no longer exists", async () => {
    deps.getSession.mockResolvedValue(createSession());
    deps.worktreeExistsAtPath.mockResolvedValue(false);

    expect(await controller.restore(MAIN_REPO)).toBeNull();
    expect(deps.deleteSession).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("discards a session when the main repo is in detached HEAD", async () => {
    deps.getSession.mockResolvedValue(createSession());
    deps.getCurrentBranch.mockResolvedValue(null);

    expect(await controller.restore(MAIN_REPO)).toBeNull();
    expect(deps.deleteSession).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("restores and starts syncing when the focused branch is still checked out", async () => {
    const session = createSession();
    deps.getSession.mockResolvedValue(session);
    deps.getCurrentBranch.mockResolvedValue("feature");

    const result = await controller.restore(MAIN_REPO);

    expect(result).toEqual(session);
    expect(deps.startSync).toHaveBeenCalledWith(MAIN_REPO, WORKTREE);
    expect(deps.startWatchingMainRepo).toHaveBeenCalledWith(MAIN_REPO);
  });

  it("adopts a renamed branch when the commit still matches the session", async () => {
    deps.getSession.mockResolvedValue(createSession({ commitSha: "sha-keep" }));
    deps.getCurrentBranch.mockResolvedValue("feature-renamed");
    deps.getCommitSha.mockResolvedValue("sha-keep");

    const result = await controller.restore(MAIN_REPO);

    expect(result?.branch).toBe("feature-renamed");
    expect(deps.saveSession).toHaveBeenCalledWith(
      expect.objectContaining({ branch: "feature-renamed" }),
    );
  });

  it("discards a session when the branch changed and the commit diverged", async () => {
    deps.getSession.mockResolvedValue(createSession({ commitSha: "sha-old" }));
    deps.getCurrentBranch.mockResolvedValue("some-other-branch");
    deps.getCommitSha.mockResolvedValue("sha-new");

    expect(await controller.restore(MAIN_REPO)).toBeNull();
    expect(deps.deleteSession).toHaveBeenCalledWith(MAIN_REPO);
  });
});
