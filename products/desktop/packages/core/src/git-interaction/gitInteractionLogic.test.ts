import { describe, expect, it } from "vitest";
import { computeGitInteractionState } from "./gitInteractionLogic";

type GitState = Parameters<typeof computeGitInteractionState>[0];

function makeState(overrides: Partial<GitState> = {}): GitState {
  return {
    repoPath: "/test/repo",
    isRepo: true,
    isRepoLoading: false,
    hasChanges: false,
    aheadOfRemote: 0,
    behind: 0,
    aheadOfDefault: 0,
    hasRemote: true,
    isFeatureBranch: true,
    currentBranch: "feature/test",
    defaultBranch: "main",
    ghStatus: { installed: true, authenticated: true },
    repoInfo: { owner: "test", repo: "test" },
    prStatus: null,
    isOnline: true,
    ...overrides,
  };
}

function actionIds(result: ReturnType<typeof computeGitInteractionState>) {
  return result.actions.map((a) => a.id);
}

describe("computeGitInteractionState", () => {
  describe("on default branch with changes", () => {
    it("returns create-pr as primary action", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: true,
        }),
      );
      expect(result.primaryAction.id).toBe("create-pr");
    });

    it("falls back to branch-here without GitHub remote", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          defaultBranch: null,
          repoInfo: null,
          hasChanges: true,
        }),
      );
      expect(result.primaryAction.id).toBe("branch-here");
    });

    it("includes create-pr, branch, and commit in actions", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: true,
        }),
      );
      expect(actionIds(result)).toEqual(["create-pr", "branch-here", "commit"]);
    });

    it("disables push and pr with feature branch message", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: true,
        }),
      );
      expect(result.pushDisabledReason).toBe("Create a feature branch first.");
    });

    it("is not detected as detached head", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: true,
        }),
      );
      expect(result.isDetachedHead).toBe(false);
    });
  });

  describe("on default branch without changes", () => {
    it("returns branch-here as primary when nothing to ship", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: false,
        }),
      );
      expect(result.primaryAction.id).toBe("branch-here");
    });

    it("returns only branch-here action", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: false,
        }),
      );
      expect(actionIds(result)).toEqual(["branch-here"]);
    });
  });

  describe("on default branch with ahead commits but no changes", () => {
    it("returns branch-here as primary", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: false,
          hasChanges: false,
          aheadOfRemote: 2,
        }),
      );
      // On default branch without changes, only branch-here is shown
      expect(result.primaryAction.id).toBe("branch-here");
    });
  });

  describe("on feature branch with changes", () => {
    it("returns create-pr as primary action", () => {
      const result = computeGitInteractionState(
        makeState({ currentBranch: "feature/test", hasChanges: true }),
      );
      expect(result.primaryAction.id).toBe("create-pr");
    });

    it("returns create-pr plus granular actions", () => {
      const result = computeGitInteractionState(
        makeState({ currentBranch: "feature/test", hasChanges: true }),
      );
      expect(actionIds(result)).toEqual(["create-pr", "commit", "push"]);
    });
  });

  describe("on feature branch with existing PR", () => {
    it("returns commit as primary when PR exists and there are uncommitted changes", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "feature/test",
          hasChanges: true,
          prStatus: {
            prExists: true,
            baseBranch: "main",
            headBranch: "feature/test",
            prUrl: "https://github.com/test/test/pull/1",
          },
        }),
      );
      expect(result.primaryAction.id).toBe("commit");
    });

    it("returns push as primary when PR exists and there are unpushed commits", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "feature/test",
          hasChanges: false,
          aheadOfRemote: 2,
          prStatus: {
            prExists: true,
            baseBranch: "main",
            headBranch: "feature/test",
            prUrl: "https://github.com/test/test/pull/1",
          },
        }),
      );
      expect(result.primaryAction.id).toBe("push");
    });

    it("returns view-pr as primary when PR exists and tree is clean", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "feature/test",
          hasChanges: false,
          aheadOfDefault: 3,
          prStatus: {
            prExists: true,
            baseBranch: "main",
            headBranch: "feature/test",
            prUrl: "https://github.com/test/test/pull/1",
          },
        }),
      );
      expect(result.primaryAction.id).toBe("view-pr");
    });

    it("excludes create-pr from actions when a PR already exists", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "feature/test",
          hasChanges: true,
          prStatus: {
            prExists: true,
            baseBranch: "main",
            headBranch: "feature/test",
            prUrl: "https://github.com/test/test/pull/1",
          },
        }),
      );
      expect(actionIds(result)).not.toContain("create-pr");
      expect(actionIds(result)).toContain("view-pr");
    });
  });

  describe("detached HEAD", () => {
    it("returns branch-here as only action", () => {
      const result = computeGitInteractionState(
        makeState({ currentBranch: null }),
      );
      expect(result.primaryAction.id).toBe("branch-here");
      expect(actionIds(result)).toEqual(["branch-here"]);
    });

    it("is detected as detached head", () => {
      const result = computeGitInteractionState(
        makeState({ currentBranch: null }),
      );
      expect(result.isDetachedHead).toBe(true);
    });
  });

  describe("isFeatureBranch true even on main", () => {
    it("returns create-pr as primary", () => {
      const result = computeGitInteractionState(
        makeState({
          currentBranch: "main",
          isFeatureBranch: true,
          hasChanges: true,
        }),
      );
      expect(result.primaryAction.id).toBe("create-pr");
    });
  });

  describe("not a repo", () => {
    it("disables all actions", () => {
      const result = computeGitInteractionState(
        makeState({ isRepo: false, currentBranch: null }),
      );
      expect(result.primaryAction.enabled).toBe(false);
    });
  });

  describe("offline", () => {
    it.each([
      {
        action: "push",
        field: "pushDisabledReason" as const,
        overrides: {
          currentBranch: "feature/test",
          hasChanges: false,
          aheadOfRemote: 2,
        } satisfies Partial<GitState>,
      },
      {
        action: "create-pr",
        field: "createPrDisabledReason" as const,
        overrides: {
          currentBranch: "feature/test",
          hasChanges: true,
        } satisfies Partial<GitState>,
      },
    ])(
      "gates $action with a no-internet reason while offline",
      ({ field, overrides }) => {
        const result = computeGitInteractionState(
          makeState({ ...overrides, isOnline: false }),
        );
        expect(result[field]).toBe("No internet connection");
      },
    );

    it.each([
      {
        action: "commit",
        overrides: {
          currentBranch: "feature/test",
          hasChanges: true,
        } satisfies Partial<GitState>,
      },
      {
        action: "branch-here",
        overrides: { currentBranch: null } satisfies Partial<GitState>,
      },
    ])(
      "still allows the local $action action while offline",
      ({ action, overrides }) => {
        const result = computeGitInteractionState(
          makeState({ ...overrides, isOnline: false }),
        );
        const found = result.actions.find((a) => a.id === action);
        expect(found?.enabled).toBe(true);
        expect(found?.disabledReason).toBeNull();
      },
    );
  });
});
