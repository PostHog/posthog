import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { execGit } from "@posthog/git/git-exec";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../utils/github-token", () => ({
  resolveGithubToken: vi.fn(() => undefined),
}));

const { cloneRepoTool, cloneRoot, GITHUB_AUTH_CONFIG_KEY } = await import(
  "./clone-repo"
);

const REPO_URL = "https://github.com/PostHog/posthog.git";

describe("clone_repo", () => {
  let cwd: string;
  let sourcePath: string;
  let targetPath: string;
  let previousConfigGlobal: string | undefined;
  let previousIsSandbox: string | undefined;

  async function git(args: string[], repoPath: string): Promise<string> {
    const result = await execGit(args, { cwd: repoPath });
    if (result.exitCode !== 0) {
      throw new Error(result.stderr || result.error);
    }
    return result.stdout.trim();
  }

  beforeEach(async () => {
    previousIsSandbox = process.env.IS_SANDBOX;
    delete process.env.IS_SANDBOX;
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
    if (previousIsSandbox === undefined) {
      delete process.env.IS_SANDBOX;
    } else {
      process.env.IS_SANDBOX = previousIsSandbox;
    }
    if (previousConfigGlobal === undefined) {
      delete process.env.GIT_CONFIG_GLOBAL;
    } else {
      process.env.GIT_CONFIG_GLOBAL = previousConfigGlobal;
    }
    await rm(cwd, { recursive: true, force: true });
  });

  it("uses the snapshotted repository root in cloud sandboxes", () => {
    process.env.IS_SANDBOX = "1";

    expect(cloneRoot("/tmp/another-directory")).toBe("/tmp/workspace/repos");
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

  // Regression: a tag leaves a detached HEAD, where rev-parse --abbrev-ref
  // prints the literal "HEAD"; the message must name the requested ref.
  it("reports the requested ref when checking out a tag", async () => {
    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog", branch: "v1" },
    );

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain("on branch v1");
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
    const env = {
      GIT_CONFIG_COUNT: "1",
      GIT_CONFIG_KEY_0: GITHUB_AUTH_CONFIG_KEY,
      GIT_CONFIG_VALUE_0: "AUTHORIZATION: basic placeholder",
    };
    const urlmatch = async (url: string): Promise<string> =>
      (await execGit(["config", "--get-urlmatch", "http", url], { env }))
        .stdout;

    expect(await urlmatch("https://github.com/PostHog/posthog.git")).toContain(
      "AUTHORIZATION: basic",
    );
    expect(await urlmatch("https://evil.example.com/x.git")).toBe("");
  });

  // Regression: a slug like "PostHog/.." collapses through path.join onto the
  // whole repos/ tree, and a clone failure there would rm -rf every prior
  // checkout. The full input matrix lives in parseGithubUrl's own tests; this
  // guards the tool's wiring to it.
  it("rejects a traversal slug without touching the workspace", async () => {
    const keptCheckout = path.join(cwd, "repos", "keep");
    await mkdir(keptCheckout, { recursive: true });

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "git@github.com:PostHog/.." },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(keptCheckout)).toBe(true);
  });

  it("rejects an owner directory that escapes through a symlink", async () => {
    const externalPath = path.join(cwd, "external");
    await mkdir(path.join(cwd, "repos"), { recursive: true });
    await mkdir(externalPath);
    await symlink(externalPath, path.join(cwd, "repos", "PostHog"));

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(path.join(externalPath, "posthog"))).toBe(false);
  });

  it("rejects a clone root symlink", async () => {
    const externalPath = path.join(cwd, "external");
    await mkdir(externalPath);
    await symlink(externalPath, path.join(cwd, "repos"));

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(path.join(externalPath, "PostHog"))).toBe(false);
  });

  it("rejects an existing target that escapes through a symlink", async () => {
    const externalPath = path.join(cwd, "external");
    await mkdir(path.join(cwd, "repos", "PostHog"), { recursive: true });
    await mkdir(externalPath);
    await symlink(externalPath, targetPath);

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(path.join(externalPath, ".git"))).toBe(false);
  });

  it("does not follow an existing target symlink within the clone root", async () => {
    const linkedPath = path.join(cwd, "repos", "Other", "keep");
    const workPath = path.join(linkedPath, "work-in-progress.md");
    await mkdir(linkedPath, { recursive: true });
    await writeFile(workPath, "unsaved edits\n");
    await mkdir(path.dirname(targetPath), { recursive: true });
    await symlink(linkedPath, targetPath);

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(workPath)).toBe(true);
  });

  it("reports filesystem setup failures separately", async () => {
    await writeFile(path.join(cwd, "repos"), "not a directory\n");

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("couldn't prepare");
    expect(result.content[0].text).not.toContain("escapes");
  });

  // Regression: a reuse-path failure used to fail every subsequent call for
  // the same repo, with no way to force a fresh clone.
  it("re-clones a wedged checkout that holds no local work", async () => {
    await mkdir(targetPath, { recursive: true });
    await git(["init", "."], targetPath);

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBeUndefined();
    expect(
      await git(["rev-parse", "--is-shallow-repository"], targetPath),
    ).toBe("true");
  });

  // The self-heal above must never cost the agent uncommitted work.
  it("keeps a wedged checkout that holds local work", async () => {
    await mkdir(targetPath, { recursive: true });
    await git(["init", "."], targetPath);
    const workPath = path.join(targetPath, "work-in-progress.md");
    await writeFile(workPath, "unsaved edits\n");

    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(workPath)).toBe(true);
  });

  it("cleans up the target after a failed clone so a retry starts fresh", async () => {
    const result = await cloneRepoTool.handler(
      { cwd, token: "test-token" },
      { repo: "PostHog/posthog", branch: "does-not-exist" },
    );

    expect(result.isError).toBe(true);
    expect(existsSync(targetPath)).toBe(false);
  });

  // Regression: without per-target serialization the loser of the race rm -rfs
  // the winner's in-progress checkout from its failure path.
  it("serializes concurrent clones of the same repo", async () => {
    const [first, second] = await Promise.all([
      cloneRepoTool.handler(
        { cwd, token: "test-token" },
        { repo: "PostHog/posthog" },
      ),
      cloneRepoTool.handler(
        { cwd, token: "test-token" },
        { repo: "PostHog/posthog" },
      ),
    ]);

    expect(first.isError).toBeUndefined();
    expect(second.isError).toBeUndefined();
    expect(
      await git(["rev-parse", "--is-shallow-repository"], targetPath),
    ).toBe("true");
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
