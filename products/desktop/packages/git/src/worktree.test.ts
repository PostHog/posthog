import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createGitClient } from "./client";
import { armProcessTimeout, KILL_GRACE_MS, WorktreeManager } from "./worktree";

async function initBareRemote(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "posthog-code-remote-"));
  const git = createGitClient(dir);
  await git.init(["--bare", "--initial-branch", "main"]);
  return dir;
}

async function initLocalClone(remoteDir: string): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "posthog-code-local-"));
  const git = createGitClient(dir);
  await git.clone(remoteDir, dir);
  await git.addConfig("user.name", "Test");
  await git.addConfig("user.email", "test@example.com");
  await git.addConfig("commit.gpgsign", "false");
  return dir;
}

async function commit(repoDir: string, file: string, content: string) {
  await writeFile(path.join(repoDir, file), content);
  const git = createGitClient(repoDir);
  await git.add([file]);
  await git.commit(`add ${file}`);
}

async function shaOfBranch(repoDir: string, ref: string): Promise<string> {
  const git = createGitClient(repoDir);
  return (await git.revparse([ref])).trim();
}

describe("WorktreeManager.createWorktree fetchBeforeCreate", () => {
  let remoteDir: string;
  let localDir: string;
  let worktreeBaseDir: string;

  beforeEach(async () => {
    remoteDir = await initBareRemote();

    // Seed the remote with an initial commit on `main` so other clones can
    // fetch a real tip.
    const seedDir = await mkdtemp(path.join(tmpdir(), "posthog-code-seed-"));
    const seedGit = createGitClient(seedDir);
    await seedGit.init(["--initial-branch", "main"]);
    await seedGit.addConfig("user.name", "Test");
    await seedGit.addConfig("user.email", "test@example.com");
    await seedGit.addConfig("commit.gpgsign", "false");
    await commit(seedDir, "initial.txt", "initial\n");
    await seedGit.addRemote("origin", remoteDir);
    await seedGit.push(["origin", "main"]);
    await rm(seedDir, { recursive: true, force: true });

    localDir = await initLocalClone(remoteDir);
    worktreeBaseDir = await mkdtemp(path.join(tmpdir(), "posthog-code-wts-"));
  });

  afterEach(async () => {
    for (const d of [remoteDir, localDir, worktreeBaseDir]) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it.each([
    {
      name: "without fetchBeforeCreate, worktree is based on the stale local ref",
      fetchBeforeCreate: false,
      expectRemoteTip: false,
    },
    {
      name: "with fetchBeforeCreate, worktree starts at the remote tip",
      fetchBeforeCreate: true,
      expectRemoteTip: true,
    },
  ])("$name", async ({ fetchBeforeCreate, expectRemoteTip }) => {
    // Advance the remote: push a new commit from a separate clone.
    const otherDir = await initLocalClone(remoteDir);
    await commit(otherDir, "remote-new.txt", "remote-new\n");
    const otherGit = createGitClient(otherDir);
    await otherGit.push(["origin", "main"]);
    const remoteTip = await shaOfBranch(otherDir, "main");
    await rm(otherDir, { recursive: true, force: true });

    const localTipBefore = await shaOfBranch(localDir, "main");
    expect(localTipBefore).not.toBe(remoteTip);

    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });
    const info = await manager.createWorktree({
      baseBranch: "main",
      fetchBeforeCreate,
    });

    const worktreeHead = await shaOfBranch(info.worktreePath, "HEAD");
    if (expectRemoteTip) {
      expect(worktreeHead).toBe(remoteTip);
    } else {
      expect(worktreeHead).toBe(localTipBefore);
      expect(worktreeHead).not.toBe(remoteTip);
    }

    // Local `main` should never be mutated — only `origin/main` advances on fetch.
    const localMainAfter = await shaOfBranch(localDir, "main");
    expect(localMainAfter).toBe(localTipBefore);
  });

  it("with fetchBeforeCreate and an unreachable remote, falls back to local base", async () => {
    // Point origin at a directory that doesn't exist so the fetch fails.
    const git = createGitClient(localDir);
    await git.remote(["set-url", "origin", "/nonexistent/path/to/remote"]);

    const localTipBefore = await shaOfBranch(localDir, "main");

    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });
    const info = await manager.createWorktree({
      baseBranch: "main",
      fetchBeforeCreate: true,
    });

    const worktreeHead = await shaOfBranch(info.worktreePath, "HEAD");
    expect(worktreeHead).toBe(localTipBefore);
  });
});

async function dirExists(p: string): Promise<boolean> {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

// The git-worktree slice moved the worktree add/list/remove/prune commands into
// ws-server services that consume @posthog/git WorktreeManager. This is the
// real-git headless smoke for that command lifecycle (acceptance: "smoke test
// the moved commands").
describe("WorktreeManager lifecycle (add / exists / list / remove / prune)", () => {
  let remoteDir: string;
  let localDir: string;
  let worktreeBaseDir: string;

  beforeEach(async () => {
    remoteDir = await initBareRemote();

    const seedDir = await mkdtemp(path.join(tmpdir(), "posthog-code-seed-"));
    const seedGit = createGitClient(seedDir);
    await seedGit.init(["--initial-branch", "main"]);
    await seedGit.addConfig("user.name", "Test");
    await seedGit.addConfig("user.email", "test@example.com");
    await seedGit.addConfig("commit.gpgsign", "false");
    await commit(seedDir, "initial.txt", "initial\n");
    await seedGit.addRemote("origin", remoteDir);
    await seedGit.push(["origin", "main"]);
    await rm(seedDir, { recursive: true, force: true });

    // realpath so the paths match what `git worktree list` reports (on macOS
    // /tmp is a symlink to /private/tmp); listWorktrees filters by path prefix.
    localDir = await realpath(await initLocalClone(remoteDir));
    worktreeBaseDir = await realpath(
      await mkdtemp(path.join(tmpdir(), "posthog-code-wts-")),
    );
  });

  afterEach(async () => {
    for (const d of [remoteDir, localDir, worktreeBaseDir]) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("adds a worktree on disk and removes it again", async () => {
    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });

    const info = await manager.createWorktree({ baseBranch: "main" });

    expect(await dirExists(info.worktreePath)).toBe(true);
    expect(await manager.worktreeExists(info.worktreeName)).toBe(true);
    expect(await shaOfBranch(info.worktreePath, "HEAD")).toBe(
      await shaOfBranch(localDir, "main"),
    );

    await manager.deleteWorktree(info.worktreePath);

    expect(await dirExists(info.worktreePath)).toBe(false);
    expect(await manager.worktreeExists(info.worktreeName)).toBe(false);
  });

  it("lists a branched worktree and prunes it as orphaned", async () => {
    await createGitClient(localDir).branch(["feature"]);

    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });
    const info = await manager.createWorktreeForExistingBranch("feature");

    const listed = await manager.listWorktrees();
    expect(listed.map((w) => w.worktreePath)).toContain(info.worktreePath);
    expect(
      listed.find((w) => w.worktreePath === info.worktreePath)?.branchName,
    ).toBe("feature");

    // Nothing is associated -> the branched worktree is orphaned and pruned.
    const { deleted, errors } = await manager.cleanupOrphanedWorktrees([]);

    expect(errors).toEqual([]);
    expect(deleted).toContain(info.worktreePath);
    expect(await dirExists(info.worktreePath)).toBe(false);
    expect(await manager.listWorktrees()).toEqual([]);
  });
});

describe("WorktreeManager worktree link/include processing", () => {
  let remoteDir: string;
  let localDir: string;
  let worktreeBaseDir: string;

  beforeEach(async () => {
    remoteDir = await initBareRemote();

    const seedDir = await mkdtemp(path.join(tmpdir(), "posthog-code-seed-"));
    const seedGit = createGitClient(seedDir);
    await seedGit.init(["--initial-branch", "main"]);
    await seedGit.addConfig("user.name", "Test");
    await seedGit.addConfig("user.email", "test@example.com");
    await seedGit.addConfig("commit.gpgsign", "false");
    await writeFile(
      path.join(seedDir, ".gitignore"),
      ".claude/\n.env\n.envrc\nCLAUDE.local.md\nnode_modules/\n",
    );
    await writeFile(path.join(seedDir, ".worktreelink"), "# secrets\n.envrc\n");
    await writeFile(path.join(seedDir, ".worktreeinclude"), ".env\n");
    await seedGit.add([".gitignore", ".worktreelink", ".worktreeinclude"]);
    await seedGit.commit("add worktree config");
    await seedGit.addRemote("origin", remoteDir);
    await seedGit.push(["origin", "main"]);
    await rm(seedDir, { recursive: true, force: true });

    localDir = await realpath(await initLocalClone(remoteDir));
    worktreeBaseDir = await realpath(
      await mkdtemp(path.join(tmpdir(), "posthog-code-wts-")),
    );

    await writeFile(path.join(localDir, ".env"), "secret\n");
    await writeFile(path.join(localDir, ".envrc"), "export FOO=1\n");
    await mkdir(path.join(localDir, ".claude"));
    await writeFile(
      path.join(localDir, ".claude", "settings.local.json"),
      "{}\n",
    );
    await writeFile(path.join(localDir, "CLAUDE.local.md"), "local rules\n");
    await mkdir(path.join(localDir, "node_modules", "dep"), {
      recursive: true,
    });
    await writeFile(
      path.join(localDir, "node_modules", "dep", ".env"),
      "dep\n",
    );
    await writeFile(
      path.join(localDir, "node_modules", "dep", ".envrc"),
      "dep\n",
    );
  });

  afterEach(async () => {
    for (const d of [remoteDir, localDir, worktreeBaseDir]) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("links and copies matching gitignored files but never reaches into standard-ignored trees", async () => {
    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });

    const info = await manager.createWorktree({ baseBranch: "main" });

    const linked = await lstat(path.join(info.worktreePath, ".envrc"));
    expect(linked.isSymbolicLink()).toBe(true);

    const copied = await readFile(
      path.join(info.worktreePath, ".env"),
      "utf-8",
    );
    expect(copied).toBe("secret\n");

    // Regression: matches buried in node_modules used to be copied, which both
    // walked the whole ignored tree and pre-created node_modules/ in the fresh
    // worktree (defeating repos' own post-checkout bootstrap checks).
    expect(await dirExists(path.join(info.worktreePath, "node_modules"))).toBe(
      false,
    );
    expect(await dirExists(path.join(info.worktreePath, ".claude"))).toBe(
      false,
    );

    const localInstructions = await lstat(
      path.join(info.worktreePath, "CLAUDE.local.md"),
    );
    expect(localInstructions.isSymbolicLink()).toBe(true);
  });

  it("links .claude when explicitly configured", async () => {
    await writeFile(
      path.join(localDir, ".worktreelink"),
      "# secrets\n.envrc\n.claude\n",
    );
    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });

    const info = await manager.createWorktree({ baseBranch: "main" });

    const linked = await lstat(path.join(info.worktreePath, ".claude"));
    expect(linked.isSymbolicLink()).toBe(true);
  });
});

describe("WorktreeManager.sweepTrash", () => {
  it("removes trashed worktrees left behind by interrupted deletes", async () => {
    const worktreeBaseDir = await mkdtemp(
      path.join(tmpdir(), "posthog-code-wts-"),
    );
    const trashDir = path.join(worktreeBaseDir, ".trash");
    await mkdir(path.join(trashDir, "stale-worktree"), { recursive: true });
    await writeFile(path.join(trashDir, "stale-worktree", "file.txt"), "x\n");

    const manager = new WorktreeManager({
      mainRepoPath: "/nonexistent-main-repo",
      worktreeBasePath: worktreeBaseDir,
    });
    await manager.sweepTrash();

    expect(await dirExists(trashDir)).toBe(false);
    await rm(worktreeBaseDir, { recursive: true, force: true });
  });
});

describe("WorktreeManager.createWorktreeForRemoteBranch", () => {
  let remoteDir: string;
  let localDir: string;
  let worktreeBaseDir: string;

  beforeEach(async () => {
    remoteDir = await initBareRemote();

    const seedDir = await mkdtemp(path.join(tmpdir(), "posthog-code-seed-"));
    const seedGit = createGitClient(seedDir);
    await seedGit.init(["--initial-branch", "main"]);
    await seedGit.addConfig("user.name", "Test");
    await seedGit.addConfig("user.email", "test@example.com");
    await seedGit.addConfig("commit.gpgsign", "false");
    await commit(seedDir, "initial.txt", "initial\n");
    await seedGit.addRemote("origin", remoteDir);
    await seedGit.push(["origin", "main"]);

    // Push a branch that will only exist on the remote from the local clone's POV.
    await seedGit.checkoutLocalBranch("contributor/pr");
    await commit(seedDir, "pr.txt", "pr content\n");
    await seedGit.push(["origin", "contributor/pr"]);

    await rm(seedDir, { recursive: true, force: true });

    localDir = await realpath(await initLocalClone(remoteDir));
    worktreeBaseDir = await realpath(
      await mkdtemp(path.join(tmpdir(), "posthog-code-wts-")),
    );
  });

  afterEach(async () => {
    for (const d of [remoteDir, localDir, worktreeBaseDir]) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it("fetches a remote-only branch and creates a tracking worktree", async () => {
    const localBranches = await createGitClient(localDir).branch();
    expect(localBranches.all).not.toContain("contributor/pr");

    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });

    const info = await manager.createWorktreeForRemoteBranch("contributor/pr");

    expect(await dirExists(info.worktreePath)).toBe(true);
    expect(info.branchName).toBe("contributor/pr");

    const remoteTip = await shaOfBranch(localDir, "origin/contributor/pr");
    const worktreeHead = await shaOfBranch(info.worktreePath, "HEAD");
    expect(worktreeHead).toBe(remoteTip);

    const upstream = (
      await createGitClient(info.worktreePath).revparse([
        "--abbrev-ref",
        "contributor/pr@{upstream}",
      ])
    ).trim();
    expect(upstream).toBe("origin/contributor/pr");
  });

  it("rejects when the remote branch cannot be fetched", async () => {
    // Point origin at a path that does not exist so the fetch fails.
    await createGitClient(localDir).remote([
      "set-url",
      "origin",
      "/nonexistent/path/to/remote",
    ]);

    const manager = new WorktreeManager({
      mainRepoPath: localDir,
      worktreeBasePath: worktreeBaseDir,
    });

    await expect(
      manager.createWorktreeForRemoteBranch("contributor/pr"),
    ).rejects.toThrow(/Failed to fetch branch 'contributor\/pr'/);
  });
});

describe("armProcessTimeout", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function fakeProc(): { kill: ReturnType<typeof vi.fn> } {
    return { kill: vi.fn() };
  }

  it("does not kill the process before the timeout elapses", () => {
    vi.useFakeTimers();
    const proc = fakeProc();
    const timeout = armProcessTimeout(proc as never, 1000);

    vi.advanceTimersByTime(999);

    expect(proc.kill).not.toHaveBeenCalled();
    expect(timeout.timedOut()).toBe(false);
    timeout.clear();
  });

  it("clear() before the timeout prevents any kill", () => {
    vi.useFakeTimers();
    const proc = fakeProc();
    const timeout = armProcessTimeout(proc as never, 1000);

    timeout.clear();
    vi.advanceTimersByTime(10_000);

    expect(proc.kill).not.toHaveBeenCalled();
    expect(timeout.timedOut()).toBe(false);
  });

  it("SIGTERMs on timeout then escalates to SIGKILL after the grace period", () => {
    vi.useFakeTimers();
    const proc = fakeProc();
    const timeout = armProcessTimeout(proc as never, 1000);

    vi.advanceTimersByTime(1000);
    expect(timeout.timedOut()).toBe(true);
    expect(proc.kill).toHaveBeenCalledWith("SIGTERM");

    vi.advanceTimersByTime(KILL_GRACE_MS);
    expect(proc.kill).toHaveBeenCalledWith("SIGKILL");
  });

  it("clear() after the timeout cancels the pending SIGKILL", () => {
    vi.useFakeTimers();
    const proc = fakeProc();
    const timeout = armProcessTimeout(proc as never, 1000);

    vi.advanceTimersByTime(1000);
    expect(proc.kill).toHaveBeenCalledWith("SIGTERM");

    timeout.clear();
    vi.advanceTimersByTime(10_000);

    expect(proc.kill).not.toHaveBeenCalledWith("SIGKILL");
  });
});
