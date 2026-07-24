import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createSignedCommit = vi.fn();
const reportCommitArtefacts = vi.fn();
const reportTaskRunBranch = vi.fn();

vi.mock("@posthog/git/signed-commit", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/git/signed-commit")>();
  return {
    ...actual,
    createSignedCommit: (...args: unknown[]) => createSignedCommit(...args),
  };
});

vi.mock("../../../signed-commit-artefacts", () => ({
  reportCommitArtefacts: (...args: unknown[]) => reportCommitArtefacts(...args),
  reportTaskRunBranch: (...args: unknown[]) => reportTaskRunBranch(...args),
}));

// Importing the tool after the mock so its transitive `createSignedCommit`
// reference resolves to the mock above.
const { signedCommitTool } = await import("./signed-commit");

describe("signed-commit tool handler", () => {
  const savedSandbox = process.env.IS_SANDBOX;

  beforeEach(() => {
    createSignedCommit.mockReset();
    reportCommitArtefacts.mockReset();
    reportTaskRunBranch.mockReset();
    createSignedCommit.mockResolvedValue({
      branch: "posthog-code/feature",
      repository: "x/y",
      commits: [
        { sha: "deadbeef", url: "https://github.com/x/y/commit/deadbeef" },
      ],
    });
  });

  afterEach(() => {
    if (savedSandbox === undefined) {
      delete process.env.IS_SANDBOX;
    } else {
      process.env.IS_SANDBOX = savedSandbox;
    }
  });

  it("defaults to the session cwd when args.cwd is absent", async () => {
    await signedCommitTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      { message: "chore: bump" },
    );
    const [ctx] = createSignedCommit.mock.calls[0];
    expect(ctx.cwd).toBe("/tmp/workspace/repos/posthog/code");
  });

  it("uses an absolute args.cwd verbatim so a sibling clone is reachable", async () => {
    await signedCommitTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      {
        message: "chore: bump",
        cwd: "/tmp/workspace/repos/posthog/posthog",
      },
    );
    const [ctx] = createSignedCommit.mock.calls[0];
    expect(ctx.cwd).toBe("/tmp/workspace/repos/posthog/posthog");
  });

  it("resolves a relative args.cwd against the session cwd", async () => {
    await signedCommitTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      { message: "chore: bump", cwd: "../posthog" },
    );
    const [ctx] = createSignedCommit.mock.calls[0];
    expect(ctx.cwd).toBe("/tmp/workspace/repos/posthog/posthog");
  });

  it("does not forward cwd to createSignedCommit input", async () => {
    await signedCommitTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      { message: "chore: bump", cwd: "/elsewhere" },
    );
    const [, input] = createSignedCommit.mock.calls[0];
    expect(input).not.toHaveProperty("cwd");
    expect(input).toEqual({ message: "chore: bump" });
  });

  it("forwards baseBranch from the tool context", async () => {
    await signedCommitTool.handler(
      {
        cwd: "/tmp/workspace/repos/posthog/code",
        token: "ghs_x",
        baseBranch: "master",
      },
      { message: "chore: bump" },
    );
    const [ctx] = createSignedCommit.mock.calls[0];
    expect(ctx.baseBranch).toBe("master");
  });

  it("persists the created branch for the task run", async () => {
    await signedCommitTool.handler(
      {
        cwd: "/tmp/workspace/repos/posthog/code",
        token: "ghs_x",
        taskId: "task-1",
        taskRunId: "run-1",
      },
      { message: "chore: bump" },
    );

    expect(reportTaskRunBranch).toHaveBeenCalledWith({
      taskId: "task-1",
      taskRunId: "run-1",
      branch: "posthog-code/feature",
    });
  });

  it("returns the no-token error without invoking createSignedCommit", async () => {
    const savedGh = process.env.GH_TOKEN;
    const savedGithub = process.env.GITHUB_TOKEN;
    delete process.env.GH_TOKEN;
    delete process.env.GITHUB_TOKEN;
    try {
      const result = await signedCommitTool.handler(
        { cwd: "/tmp/workspace/repos/posthog/code" },
        { message: "chore: bump" },
      );
      expect(result.isError).toBe(true);
      expect(createSignedCommit).not.toHaveBeenCalled();
    } finally {
      if (savedGh !== undefined) process.env.GH_TOKEN = savedGh;
      if (savedGithub !== undefined) process.env.GITHUB_TOKEN = savedGithub;
    }
  });
});
