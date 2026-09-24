import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { execGit } from "./git-exec";
import { GITHUB_AUTH_CONFIG_KEY } from "./github-auth";
import { getCleanEnv, getGitOperationManager } from "./operation-manager";

describe("getCleanEnv", () => {
  const original = { ...process.env };
  const scratchDirs: string[] = [];

  afterEach(async () => {
    process.env = { ...original };
    await Promise.all(
      scratchDirs
        .splice(0)
        .map((dir) => rm(dir, { recursive: true, force: true })),
    );
  });

  const scratchRepo = async (): Promise<string> => {
    const dir = await mkdtemp(path.join(tmpdir(), "op-manager-"));
    scratchDirs.push(dir);
    await execGit(["init", "--initial-branch", "main"], { cwd: dir });
    return dir;
  };

  it("stops a missing credential from opening a prompt", () => {
    delete process.env.GH_TOKEN;
    delete process.env.GITHUB_TOKEN;

    const env = getCleanEnv();

    expect(env.GIT_TERMINAL_PROMPT).toBe("0");
    expect(env.GIT_ASKPASS).toBe("");
    expect(env.GIT_CONFIG_COUNT).toBeUndefined();
  });

  it("carries the GitHub token into every git subprocess, not just clones", () => {
    process.env.GH_TOKEN = "ghs_token";

    const env = getCleanEnv();

    expect(env.GIT_CONFIG_KEY_0).toBe(GITHUB_AUTH_CONFIG_KEY);
    expect(env.GIT_CONFIG_VALUE_0).toContain("AUTHORIZATION: basic ");
  });

  // simple-git rejects GIT_CONFIG_COUNT and GIT_ASKPASS unless createGitClient
  // opts in, and it only sees them once a token is present. Asserting the env
  // alone passed while every real git call failed.
  it("spawns git successfully with the auth env applied", async () => {
    process.env.GH_TOKEN = "ghs_token";
    const repo = await scratchRepo();

    const inWorkTree = await getGitOperationManager().executeRead(repo, (git) =>
      git.raw(["rev-parse", "--is-inside-work-tree"]),
    );

    expect(inWorkTree.trim()).toBe("true");
  });
});
