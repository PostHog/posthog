import { beforeEach, describe, expect, it, vi } from "vitest";

const createSignedMerge = vi.fn();

vi.mock("@posthog/git/signed-commit", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/git/signed-commit")>();
  return {
    ...actual,
    createSignedMerge: (...args: unknown[]) => createSignedMerge(...args),
  };
});

// Importing the tool after the mock so its transitive `createSignedMerge`
// reference resolves to the mock above.
const { signedMergeTool } = await import("./signed-merge");

describe("signed-merge tool handler", () => {
  beforeEach(() => {
    createSignedMerge.mockReset();
    createSignedMerge.mockResolvedValue({
      branch: "posthog-code/feature",
      base: "master",
      merged: true,
      commit: {
        sha: "deadbeef",
        url: "https://github.com/x/y/commit/deadbeef",
      },
    });
  });

  it("defaults to the session cwd when args.cwd is absent", async () => {
    await signedMergeTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      {},
    );
    const [ctx] = createSignedMerge.mock.calls[0];
    expect(ctx.cwd).toBe("/tmp/workspace/repos/posthog/code");
  });

  it("resolves a relative args.cwd against the session cwd", async () => {
    await signedMergeTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      { cwd: "../posthog" },
    );
    const [ctx] = createSignedMerge.mock.calls[0];
    expect(ctx.cwd).toBe("/tmp/workspace/repos/posthog/posthog");
  });

  it("does not forward cwd to createSignedMerge input", async () => {
    await signedMergeTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      { base: "master", cwd: "/elsewhere" },
    );
    const [, input] = createSignedMerge.mock.calls[0];
    expect(input).not.toHaveProperty("cwd");
    expect(input).toEqual({ base: "master" });
  });

  it("forwards baseBranch from the tool context", async () => {
    await signedMergeTool.handler(
      {
        cwd: "/tmp/workspace/repos/posthog/code",
        token: "ghs_x",
        baseBranch: "master",
      },
      {},
    );
    const [ctx] = createSignedMerge.mock.calls[0];
    expect(ctx.baseBranch).toBe("master");
  });

  it("returns the no-token error without invoking createSignedMerge", async () => {
    const savedGh = process.env.GH_TOKEN;
    const savedGithub = process.env.GITHUB_TOKEN;
    delete process.env.GH_TOKEN;
    delete process.env.GITHUB_TOKEN;
    try {
      const result = await signedMergeTool.handler(
        { cwd: "/tmp/workspace/repos/posthog/code" },
        {},
      );
      expect(result.isError).toBe(true);
      expect(createSignedMerge).not.toHaveBeenCalled();
    } finally {
      if (savedGh !== undefined) process.env.GH_TOKEN = savedGh;
      if (savedGithub !== undefined) process.env.GITHUB_TOKEN = savedGithub;
    }
  });

  it("formats an up-to-date result without a commit list", async () => {
    createSignedMerge.mockResolvedValue({
      branch: "posthog-code/feature",
      base: "master",
      merged: false,
    });
    const result = await signedMergeTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      {},
    );
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain("already up to date");
  });

  it("surfaces a local-sync warning alongside the merge commit", async () => {
    createSignedMerge.mockResolvedValue({
      branch: "posthog-code/feature",
      base: "master",
      merged: true,
      commit: {
        sha: "deadbeef",
        url: "https://github.com/x/y/commit/deadbeef",
      },
      localSyncWarning: "the merge is on the remote, but syncing failed",
    });
    const result = await signedMergeTool.handler(
      { cwd: "/tmp/workspace/repos/posthog/code", token: "ghs_x" },
      {},
    );
    expect(result.content[0].text).toContain("deadbeef");
    expect(result.content[0].text).toContain("Warning:");
  });
});
