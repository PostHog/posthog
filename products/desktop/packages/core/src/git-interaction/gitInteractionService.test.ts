import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type GitInteractionEffects,
  GitInteractionService,
  type GitStagingContext,
  type IGitWriteClient,
} from "./gitInteractionService";

const stagingContext: GitStagingContext = {
  staged_file_count: 0,
  unstaged_file_count: 0,
  commit_all: true,
  staged_only: false,
};

function makeWriteClient(
  overrides: Partial<IGitWriteClient> = {},
): IGitWriteClient {
  return {
    commit: vi.fn(async () => ({
      success: true,
      message: "ok",
      commitSha: "sha",
      branch: "main",
    })),
    push: vi.fn(async () => ({ success: true, message: "ok" })),
    sync: vi.fn(async () => ({
      success: true,
      pullMessage: "ok",
      pushMessage: "ok",
    })),
    publish: vi.fn(async () => ({
      success: true,
      message: "ok",
      branch: "feature",
    })),
    createBranch: vi.fn(async () => {}),
    createPr: vi.fn(async () => ({
      success: true,
      message: "ok",
      prUrl: "https://example.test/pr/1",
      failedStep: null,
    })),
    openPr: vi.fn(async () => ({
      success: true,
      message: "ok",
      prUrl: "https://pr",
    })),
    generateCommitMessage: vi.fn(async () => ({ message: "generated" })),
    generatePrTitleAndBody: vi.fn(async () => ({ title: "t", body: "b" })),
    linkBranch: vi.fn(async () => {}),
    onCreatePrProgress: vi.fn(() => () => {}),
    ...overrides,
  };
}

function makeEffects(
  overrides: Partial<GitInteractionEffects> = {},
): GitInteractionEffects {
  return {
    trackGitAction: vi.fn(),
    trackPrCreated: vi.fn(),
    hasShippedFirstPr: vi.fn(() => true),
    markFirstPrShipped: vi.fn(),
    celebrate: vi.fn(),
    openExternalUrl: vi.fn(),
    attachPrUrlToTask: vi.fn(),
    getConversationContext: vi.fn(() => undefined),
    logError: vi.fn(),
    logWarn: vi.fn(),
    ...overrides,
  };
}

function commitInput(over: Record<string, unknown> = {}) {
  return {
    repoPath: "/repo",
    taskId: "task-1",
    message: "msg",
    stagedOnly: false,
    stagingContext,
    hasRemote: true,
    pushDisabledReason: null,
    commitPush: false,
    ...over,
  };
}

describe("GitInteractionService.runCommit", () => {
  let git: IGitWriteClient;
  let effects: GitInteractionEffects;
  let service: GitInteractionService;

  beforeEach(() => {
    git = makeWriteClient();
    effects = makeEffects();
    service = new GitInteractionService(git, effects);
  });

  it("commits and tallies success", async () => {
    const result = await service.runCommit(commitInput());
    expect(result.outcome).toBe("committed");
    expect(effects.trackGitAction).toHaveBeenCalledWith(
      "task-1",
      "commit",
      true,
      stagingContext,
    );
  });

  it("blocks commit-push when push is disabled", async () => {
    const result = await service.runCommit(
      commitInput({ commitPush: true, pushDisabledReason: "behind remote" }),
    );
    expect(result).toEqual({ outcome: "error", message: "behind remote" });
    expect(git.commit).not.toHaveBeenCalled();
  });

  it("generates a fallback message when empty", async () => {
    const result = await service.runCommit(commitInput({ message: "" }));
    expect(git.generateCommitMessage).toHaveBeenCalled();
    expect(result.outcome).toBe("committed");
    if (result.outcome === "committed") {
      expect(result.generatedMessage).toBe("generated");
    }
  });

  it("returns generate-failed when fallback yields no message", async () => {
    git = makeWriteClient({
      generateCommitMessage: vi.fn(async () => ({ message: "" })),
    });
    service = new GitInteractionService(git, effects);
    const result = await service.runCommit(commitInput({ message: "" }));
    expect(result.outcome).toBe("generate-failed");
  });

  it("chains into push on commit-push", async () => {
    const result = await service.runCommit(commitInput({ commitPush: true }));
    expect(git.push).toHaveBeenCalledTimes(1);
    if (result.outcome === "committed") {
      expect(result.next?.mode).toBe("push");
      expect(result.next?.result.outcome).toBe("success");
    }
  });

  it("chains into publish when no remote", async () => {
    const result = await service.runCommit(
      commitInput({ commitPush: true, hasRemote: false }),
    );
    expect(git.publish).toHaveBeenCalledTimes(1);
    if (result.outcome === "committed") {
      expect(result.next?.mode).toBe("publish");
    }
  });
});

describe("GitInteractionService.runPush", () => {
  it("dispatches sync mode", async () => {
    const git = makeWriteClient();
    const service = new GitInteractionService(git, makeEffects());
    const controller = new AbortController();
    const result = await service.runPush({
      repoPath: "/repo",
      taskId: "t",
      mode: "sync",
      signal: controller.signal,
    });
    expect(git.sync).toHaveBeenCalled();
    expect(result.outcome).toBe("success");
  });

  it("returns aborted when signal is aborted on throw", async () => {
    const controller = new AbortController();
    const git = makeWriteClient({
      push: vi.fn(async () => {
        controller.abort();
        throw new Error("aborted");
      }),
    });
    const service = new GitInteractionService(git, makeEffects());
    const result = await service.runPush({
      repoPath: "/repo",
      taskId: "t",
      mode: "push",
      signal: controller.signal,
    });
    expect(result.outcome).toBe("aborted");
  });

  it("maps sync failure messages", async () => {
    const git = makeWriteClient({
      sync: vi.fn(async () => ({
        success: false,
        pullMessage: "pull bad",
        pushMessage: "push bad",
      })),
    });
    const service = new GitInteractionService(git, makeEffects());
    const result = await service.runPush({
      repoPath: "/repo",
      taskId: "t",
      mode: "sync",
      signal: new AbortController().signal,
    });
    expect(result).toEqual({
      outcome: "error",
      message: "Pull: pull bad, Push: push bad",
    });
  });
});

describe("GitInteractionService.runBranch", () => {
  it("links branch to task on success", async () => {
    const git = makeWriteClient();
    const effects = makeEffects();
    const service = new GitInteractionService(git, effects);
    const result = await service.runBranch({
      repoPath: "/repo",
      taskId: "t",
      rawBranchName: "feature-x",
    });
    expect(result).toEqual({ outcome: "success", branchName: "feature-x" });
    expect(git.linkBranch).toHaveBeenCalledWith("t", "feature-x");
    expect(effects.trackGitAction).toHaveBeenCalledWith(
      "t",
      "branch-here",
      true,
    );
  });

  it("returns error on validation failure", async () => {
    const git = makeWriteClient();
    const service = new GitInteractionService(git, makeEffects());
    const result = await service.runBranch({
      repoPath: "/repo",
      taskId: "t",
      rawBranchName: "",
    });
    expect(result.outcome).toBe("error");
    expect(git.createBranch).not.toHaveBeenCalled();
  });
});

describe("GitInteractionService.runCreatePr", () => {
  function prInput(over: Record<string, unknown> = {}) {
    return {
      repoPath: "/repo",
      taskId: "t",
      flowId: "flow-1",
      needsBranch: true,
      branchName: "feature-x",
      currentBranch: "main",
      commitMessage: "",
      prTitle: "",
      prBody: "",
      draft: false,
      stagedOnly: false,
      stagingContext,
      onStep: vi.fn(),
      ...over,
    };
  }

  it("celebrates and tallies on first PR", async () => {
    const git = makeWriteClient();
    const effects = makeEffects({ hasShippedFirstPr: vi.fn(() => false) });
    const service = new GitInteractionService(git, effects);
    const result = await service.runCreatePr(prInput());
    expect(result.outcome).toBe("success");
    expect(effects.markFirstPrShipped).toHaveBeenCalled();
    expect(effects.celebrate).toHaveBeenCalled();
    expect(effects.trackPrCreated).toHaveBeenCalledWith("t", true);
    expect(effects.openExternalUrl).toHaveBeenCalledWith(
      "https://example.test/pr/1",
    );
    expect(effects.attachPrUrlToTask).toHaveBeenCalledWith(
      "t",
      "https://example.test/pr/1",
      undefined,
    );
    if (result.outcome === "success") {
      expect(result.linkedBranchName).toBe("feature-x");
      expect(result.branchInvalidated).toBe(true);
    }
  });

  it("does not celebrate when already shipped", async () => {
    const git = makeWriteClient();
    const effects = makeEffects({ hasShippedFirstPr: vi.fn(() => true) });
    const service = new GitInteractionService(git, effects);
    await service.runCreatePr(prInput());
    expect(effects.celebrate).not.toHaveBeenCalled();
  });

  it("unsubscribes the progress listener", async () => {
    const unsubscribe = vi.fn();
    const git = makeWriteClient({
      onCreatePrProgress: vi.fn(() => unsubscribe),
    });
    const service = new GitInteractionService(git, makeEffects());
    await service.runCreatePr(prInput());
    expect(unsubscribe).toHaveBeenCalled();
  });

  it("reports failedStep on failure", async () => {
    const git = makeWriteClient({
      createPr: vi.fn(async () => ({
        success: false,
        message: "boom",
        prUrl: null,
        failedStep: "pushing" as const,
      })),
    });
    const service = new GitInteractionService(git, makeEffects());
    const result = await service.runCreatePr(prInput());
    expect(result).toMatchObject({
      outcome: "error",
      message: "boom",
      failedStep: "pushing",
    });
  });
});
