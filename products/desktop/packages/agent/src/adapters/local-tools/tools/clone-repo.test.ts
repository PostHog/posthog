import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { execGit } from "@posthog/git/git-exec";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../utils/github-token", () => ({
  resolveGithubToken: vi.fn(() => undefined),
}));

const { cloneRepoTool, gitEnv } = await import("./clone-repo");

const REPO_URL = "https://github.com/PostHog/posthog.git";

describe("clone_repo", () => {
  let cwd: string;
  let sourcePath: string;
  let targetPath: string;
  let previousConfigGlobal: string | undefined;

  async function git(args: string[], repoPath: string): Promise<string> {
    const result = await execGit(args, { cwd: repoPath });
    if (result.exitCode !== 0) {
      throw new Error(result.stderr || result.error);
    }
    return result.stdout.trim();
  }

  beforeEach(async () => {
    cwd = await mkdtemp(path.join(tmpdir(), "posthog-code-clone-tool-"));
    sourcePath = path.join(cwd, "source");
    targetPath = path.join(cwd, "repos", "PostHog", "posthog");
    await mkdir(sourcePath, { recursive: true });

    await git(["init", "--initial-branch=master", "."], sourcePath);
    await git(["config", "user.name", "PostHog Code test"], sourcePath);
    await git(["config", "user.email", "test@posthog.com"], sourcePath);
    await git(["config", "commit.gpgsign", "false"], sourcePath);
    await writeFile(path.join(sourcePath, "README.md"), "master\n");
    await git(["add", "README.md"], sourcePath);
    await git(["commit", "-m", "initial commit"], sourcePath);
    await git(["tag", "v1"], sourcePath);
    await git(["checkout", "-b", "feature"], sourcePath);
    await writeFile(path.join(sourcePath, "README.md"), "feature\n");
    await git(["add", "README.md"], sourcePath);
    await git(["commit", "-m", "feature commit"], sourcePath);
    await git(["checkout", "master"], sourcePath);

    // Serve github.com/PostHog/posthog from the local fixture. This lands in a
    // config file rather than GIT_CONFIG_* env so the tool's own auth env (which
    // takes GIT_CONFIG_COUNT) still applies on top of it.
    const configPath = path.join(cwd, "gitconfig");
    await writeFile(
      configPath,
      `[url "${pathToFileURL(sourcePath).href}"]\n\tinsteadOf = ${REPO_URL}\n`,
    );
    previousConfigGlobal = process.env.GIT_CONFIG_GLOBAL;
    process.env.GIT_CONFIG_GLOBAL = configPath;
  });

  afterEach(async () => {
    if (previousConfigGlobal === undefined) {
      delete process.env.GIT_CONFIG_GLOBAL;
    } else {
      process.env.GIT_CONFIG_GLOBAL = previousConfigGlobal;
    }
    await rm(cwd, { recursive: true, force: true });
  });

  it("clones one commit of the requested branch, without tags or a token in origin", async () => {
    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog", branch: "feature" },
    );

    expect(result.isError).toBeUndefined();
    expect(await git(["rev-parse", "--abbrev-ref", "HEAD"], targetPath)).toBe(
      "feature",
    );
    expect(
      await git(["rev-parse", "--is-shallow-repository"], targetPath),
    ).toBe("true");
    expect(await git(["rev-list", "--count", "HEAD"], targetPath)).toBe("1");
    expect(await git(["tag", "--list"], targetPath)).toBe("");
    // The token rides in an http.extraHeader env var, so it must not have been
    // persisted into the checkout's config the way a URL credential would be.
    expect(
      await git(["config", "--get", "remote.origin.url"], targetPath),
    ).toBe(REPO_URL);
    expect(
      await git(["config", "--local", "--list"], targetPath),
    ).not.toContain("test-token");
  });

  // A retargeted origin is what turns the missing-branch fetch below into a
  // request to somewhere we never meant to talk to, carrying the token with it.
  it.each([
    {
      case: "carries embedded credentials",
      origin:
        "https://x-access-token:stale-token@github.com/PostHog/posthog.git",
    },
    {
      case: "points at another host",
      origin: "https://evil.example.com/PostHog/posthog.git",
    },
  ])("normalizes an existing clone origin that $case", async ({ origin }) => {
    await mkdir(targetPath, { recursive: true });
    await git(["init", "."], targetPath);
    await git(["remote", "add", "origin", origin], targetPath);

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBeUndefined();
    expect(
      await git(["config", "--get", "remote.origin.url"], targetPath),
    ).toBe(REPO_URL);
  });

  // Regression: an unscoped http.extraHeader is sent to every HTTP remote, so a
  // fetch against a non-GitHub origin would hand over the live token.
  it("scopes the auth header to github.com", async () => {
    const env = gitEnv("test-token");
    const urlmatch = async (url: string): Promise<string> =>
      (await execGit(["config", "--get-urlmatch", "http", url], { env }))
        .stdout;

    expect(await urlmatch("https://github.com/PostHog/posthog.git")).toContain(
      "AUTHORIZATION: basic",
    );
    expect(await urlmatch("https://evil.example.com/x.git")).toBe("");
  });

  it("fetches a missing branch into an existing shallow clone", async () => {
    await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog", branch: "master" },
    );

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog", branch: "feature" },
    );

    expect(result.isError).toBeUndefined();
    expect(await git(["rev-parse", "--abbrev-ref", "HEAD"], targetPath)).toBe(
      "feature",
    );
    expect(
      await git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        targetPath,
      ),
    ).toBe("origin/feature");
    expect(
      await git(["rev-parse", "--is-shallow-repository"], targetPath),
    ).toBe("true");
    expect(await git(["rev-list", "--count", "HEAD"], targetPath)).toBe("1");
  });
});
