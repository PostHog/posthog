import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
import { GitPrService } from "./git-pr";
import type { CreatePrHost, GitDiffSource } from "./identifiers";

const noopLogger: RootLogger = {
  debug: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  scope: () => noopLogger,
};

function makeDiffSource(over: Partial<GitDiffSource> = {}): GitDiffSource {
  return {
    getStagedDiff: vi.fn().mockResolvedValue(""),
    getUnstagedDiff: vi.fn().mockResolvedValue(""),
    getCommitConventions: vi.fn().mockResolvedValue({
      conventionalCommits: false,
      commonPrefixes: [],
      sampleMessages: [],
    }),
    getChangedFilesHead: vi.fn().mockResolvedValue([]),
    getDefaultBranch: vi.fn().mockResolvedValue("main"),
    getCurrentBranch: vi.fn().mockResolvedValue("feature"),
    getDiffAgainstRemote: vi.fn().mockResolvedValue(""),
    getCommitsBetweenBranches: vi.fn().mockResolvedValue([]),
    getPrTemplate: vi.fn().mockResolvedValue({ template: null }),
    fetchFromRemote: vi.fn().mockResolvedValue(undefined),
    ...over,
  };
}

function makeLlm(content: string) {
  return {
    prompt: vi.fn().mockResolvedValue({ content }),
  } as unknown as ConstructorParameters<typeof GitPrService>[1];
}

describe("GitPrService.generateCommitMessage", () => {
  it("returns an empty message when there is no diff and no changed files", async () => {
    const llm = makeLlm("should-not-be-used");
    const service = new GitPrService(makeDiffSource(), llm, noopLogger);

    const result = await service.generateCommitMessage("/repo");

    expect(result).toEqual({ message: "" });
    expect(llm.prompt).not.toHaveBeenCalled();
  });

  it("prompts the LLM with the staged diff and returns the trimmed message", async () => {
    const llm = makeLlm("  feat: add widget\n");
    const diffSource = makeDiffSource({
      getStagedDiff: vi.fn().mockResolvedValue("diff --git a/x b/x"),
      getChangedFilesHead: vi
        .fn()
        .mockResolvedValue([{ status: "modified", path: "x.ts" }]),
    });
    const service = new GitPrService(diffSource, llm, noopLogger);

    const result = await service.generateCommitMessage("/repo", "why context");

    expect(result).toEqual({ message: "feat: add widget" });
    const [messages, options] = (llm.prompt as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(messages[0].content).toContain("diff --git a/x b/x");
    expect(messages[0].content).toContain("modified: x.ts");
    expect(messages[0].content).toContain("why context");
    expect(options.system).toContain("commit message generator");
    expect(options.posthogProperties).toEqual({
      $ai_span_name: "commit_message",
    });
  });
});

describe("GitPrService.generatePrTitleAndBody", () => {
  it("returns empty title/body when there are no commits and no diff", async () => {
    const llm = makeLlm("unused");
    const service = new GitPrService(makeDiffSource(), llm, noopLogger);

    const result = await service.generatePrTitleAndBody("/repo");

    expect(result).toEqual({ title: "", body: "" });
    expect(llm.prompt).not.toHaveBeenCalled();
  });

  it("parses TITLE/BODY out of the LLM response", async () => {
    const llm = makeLlm(
      "TITLE: feat: add widget\n\nBODY:\nTL;DR: adds a widget.",
    );
    const diffSource = makeDiffSource({
      getCommitsBetweenBranches: vi
        .fn()
        .mockResolvedValue([{ message: "add widget" }]),
      getDiffAgainstRemote: vi.fn().mockResolvedValue("diff --git a/x b/x"),
    });
    const service = new GitPrService(diffSource, llm, noopLogger);

    const result = await service.generatePrTitleAndBody("/repo");

    expect(result.title).toBe("feat: add widget");
    expect(result.body).toBe("TL;DR: adds a widget.");
    expect(diffSource.fetchFromRemote).toHaveBeenCalledWith("/repo");
    const [, options] = (llm.prompt as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(options.posthogProperties).toEqual({
      $ai_span_name: "pr_description",
    });
  });
});

function makeHost(over: Partial<CreatePrHost> = {}): CreatePrHost {
  return {
    getSessionEnvForTask: vi.fn().mockResolvedValue(undefined),
    getCurrentBranch: vi.fn().mockResolvedValue("feature"),
    createBranch: vi.fn().mockResolvedValue(undefined),
    getChangedFilesHead: vi.fn().mockResolvedValue([]),
    getHeadSha: vi.fn().mockResolvedValue("abc1234"),
    commit: vi.fn().mockResolvedValue({ success: true, message: "committed" }),
    resetSoft: vi.fn().mockResolvedValue(undefined),
    getSyncStatus: vi.fn().mockResolvedValue({ hasRemote: true }),
    push: vi.fn().mockResolvedValue({ success: true, message: "pushed" }),
    publish: vi.fn().mockResolvedValue({ success: true, message: "published" }),
    createPrViaGh: vi.fn().mockResolvedValue({
      success: true,
      message: "Pull request created",
      prUrl: "https://github.com/o/r/pull/1",
    }),
    linkBranch: vi.fn(),
    getPrState: vi.fn().mockResolvedValue({ prStatus: "open" }),
    ...over,
  };
}

describe("GitPrService.createPr", () => {
  it("commits, pushes, creates the PR, links the branch, and reports completion", async () => {
    const host = makeHost({
      getChangedFilesHead: vi
        .fn()
        .mockResolvedValue([{ status: "modified", path: "x.ts" }]),
    });
    const service = new GitPrService(makeDiffSource(), makeLlm(""), noopLogger);
    const onProgress = vi.fn();

    const result = await service.createPr(
      {
        directoryPath: "/repo",
        commitMessage: "feat: x",
        prTitle: "feat: x",
        prBody: "body",
        taskId: "task-1",
      },
      host,
      onProgress,
    );

    expect(result.success).toBe(true);
    expect(result.prUrl).toBe("https://github.com/o/r/pull/1");
    expect(result.state).toEqual({ prStatus: "open" });
    expect(host.commit).toHaveBeenCalledWith("/repo", "feat: x", {
      stagedOnly: undefined,
      taskId: "task-1",
      env: undefined,
    });
    expect(host.push).toHaveBeenCalledWith("/repo", undefined);
    expect(host.linkBranch).toHaveBeenCalledWith("task-1", "feature", "user");
    expect(onProgress).toHaveBeenLastCalledWith(
      "complete",
      "Pull request created",
      "https://github.com/o/r/pull/1",
    );
  });

  it("publishes instead of pushing when there is no remote", async () => {
    const host = makeHost({
      getChangedFilesHead: vi.fn().mockResolvedValue([]),
      getSyncStatus: vi.fn().mockResolvedValue({ hasRemote: false }),
    });
    const service = new GitPrService(makeDiffSource(), makeLlm(""), noopLogger);

    const result = await service.createPr(
      { directoryPath: "/repo", prTitle: "t", prBody: "b" },
      host,
      vi.fn(),
    );

    expect(result.success).toBe(true);
    expect(host.publish).toHaveBeenCalledWith("/repo", undefined);
    expect(host.push).not.toHaveBeenCalled();
  });

  it("rolls back the commit and reports the failed step when push fails", async () => {
    const host = makeHost({
      getChangedFilesHead: vi
        .fn()
        .mockResolvedValue([{ status: "modified", path: "x.ts" }]),
      push: vi.fn().mockResolvedValue({ success: false, message: "boom" }),
    });
    const service = new GitPrService(makeDiffSource(), makeLlm(""), noopLogger);
    const onProgress = vi.fn();

    const result = await service.createPr(
      { directoryPath: "/repo", commitMessage: "feat: x" },
      host,
      onProgress,
    );

    expect(result.success).toBe(false);
    expect(result.message).toBe("boom");
    expect(result.failedStep).toBe("pushing");
    expect(host.resetSoft).toHaveBeenCalledWith("/repo", "abc1234");
    expect(host.createPrViaGh).not.toHaveBeenCalled();
    expect(onProgress).toHaveBeenLastCalledWith("error", "boom");
  });
});
