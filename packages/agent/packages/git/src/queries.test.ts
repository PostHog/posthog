import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import { devNull, tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createGitClient } from "./client";
import {
  addToLocalExclude,
  anyBranchRefExists,
  type ChangedFileInfo,
  computeDiffStatsFromFiles,
  detectDefaultBranch,
  getAllBranches,
  getBranchDiffPatchesByPath,
  getChangedFilesDetailed,
  getGitBusyState,
  getLinkedWorktreeMainPath,
  listAllFiles,
  remoteBranchExists,
  splitUnifiedDiffByFile,
} from "./queries";

async function setupRepo(defaultBranch = "main"): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "posthog-code-queries-"));
  const git = createGitClient(dir);
  await git.init(["--initial-branch", defaultBranch]);
  await git.addConfig("user.name", "Test");
  await git.addConfig("user.email", "test@example.com");
  await git.addConfig("commit.gpgsign", "false");
  await writeFile(path.join(dir, "file.txt"), "content\n");
  await git.add(["file.txt"]);
  await git.commit("initial");
  return dir;
}

describe("detectDefaultBranch", () => {
  let repoDir: string;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
    }
  });

  it("detects 'main' as default branch", async () => {
    repoDir = await setupRepo("main");
    const git = createGitClient(repoDir);
    const result = await detectDefaultBranch(git);
    expect(result).toBe("main");
  });

  it("detects 'master' as default branch", async () => {
    repoDir = await setupRepo("master");
    const git = createGitClient(repoDir);
    const result = await detectDefaultBranch(git);
    expect(result).toBe("master");
  });

  it("detects non-standard default branch via init.defaultBranch config", async () => {
    repoDir = await setupRepo("develop");
    const git = createGitClient(repoDir);

    // Set init.defaultBranch in the repo's local config
    await git.addConfig("init.defaultBranch", "develop");

    const result = await detectDefaultBranch(git);
    expect(result).toBe("develop");
  });

  it("falls back to current branch when no standard branch exists", async () => {
    repoDir = await setupRepo("trunk");
    const git = createGitClient(repoDir);
    const result = await detectDefaultBranch(git);
    expect(result).toBe("trunk");
  });

  it("prefers 'main' over other detection methods", async () => {
    repoDir = await setupRepo("main");
    const git = createGitClient(repoDir);

    // Create additional branches
    await git.checkoutLocalBranch("develop");
    await git.checkout("main");

    const result = await detectDefaultBranch(git);
    expect(result).toBe("main");
  });

  it("prefers remote HEAD over local detection", async () => {
    repoDir = await setupRepo("main");
    const git = createGitClient(repoDir);

    // Set up a bare remote with a non-standard default branch
    const remoteDir = await mkdtemp(
      path.join(tmpdir(), "posthog-code-remote-"),
    );
    const remoteGit = createGitClient(remoteDir);
    await remoteGit.init(["--bare", "--initial-branch", "production"]);
    await git.addRemote("origin", remoteDir);

    // Push main as production on remote and set HEAD
    await git.push(["origin", "main:production"]);
    await remoteGit.raw(["symbolic-ref", "HEAD", "refs/heads/production"]);
    await git.fetch(["origin"]);

    const result = await detectDefaultBranch(git);
    expect(result).toBe("production");

    await rm(remoteDir, { recursive: true, force: true });
  });
});

describe("splitUnifiedDiffByFile", () => {
  it("returns an empty map for empty input", () => {
    expect(splitUnifiedDiffByFile("")).toEqual(new Map());
  });

  it("splits a two-file diff keyed by post-image path", () => {
    const raw = [
      "diff --git a/one.txt b/one.txt",
      "index 0000000..1111111 100644",
      "--- a/one.txt",
      "+++ b/one.txt",
      "@@ -1 +1 @@",
      "-hello",
      "+hello world",
      "diff --git a/two.txt b/two.txt",
      "new file mode 100644",
      "--- /dev/null",
      "+++ b/two.txt",
      "@@ -0,0 +1 @@",
      "+brand new",
      "",
    ].join("\n");

    const result = splitUnifiedDiffByFile(raw);

    expect([...result.keys()]).toEqual(["one.txt", "two.txt"]);
    expect(result.get("one.txt")).toContain("diff --git a/one.txt b/one.txt");
    expect(result.get("one.txt")).toContain("+hello world");
    expect(result.get("two.txt")).toContain("diff --git a/two.txt b/two.txt");
    expect(result.get("two.txt")).toContain("+brand new");
  });

  it("keys renames by the post-rename (b/) path", () => {
    const raw = [
      "diff --git a/old.txt b/new.txt",
      "similarity index 100%",
      "rename from old.txt",
      "rename to new.txt",
      "",
    ].join("\n");

    const result = splitUnifiedDiffByFile(raw);
    expect(result.has("new.txt")).toBe(true);
    expect(result.has("old.txt")).toBe(false);
    expect(result.get("new.txt")).toContain("rename from old.txt");
  });

  it("handles binary diffs", () => {
    const raw = [
      "diff --git a/image.png b/image.png",
      "Binary files a/image.png and b/image.png differ",
      "",
    ].join("\n");

    const result = splitUnifiedDiffByFile(raw);
    expect(result.get("image.png")).toContain("Binary files");
  });
});

describe("getBranchDiffPatchesByPath", () => {
  let repoDir: string | undefined;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
      repoDir = undefined;
    }
  });

  async function setupBranchWithCommits(): Promise<{
    repoDir: string;
    remoteDir: string;
  }> {
    const workDir = await mkdtemp(path.join(tmpdir(), "posthog-code-branch-"));
    const remoteDir = await mkdtemp(path.join(tmpdir(), "posthog-code-bare-"));

    const remoteGit = createGitClient(remoteDir);
    await remoteGit.init(["--bare", "--initial-branch", "main"]);

    const git = createGitClient(workDir);
    await git.init(["--initial-branch", "main"]);
    await git.addConfig("user.name", "Test");
    await git.addConfig("user.email", "test@example.com");
    await git.addConfig("commit.gpgsign", "false");
    await git.addRemote("origin", remoteDir);

    await writeFile(path.join(workDir, "file.txt"), "line1\nline2\n");
    await git.add(["file.txt"]);
    await git.commit("initial");
    await git.push(["origin", "main"]);

    await git.checkoutLocalBranch("feature");
    await writeFile(path.join(workDir, "file.txt"), "line1\nchanged\n");
    await writeFile(path.join(workDir, "added.txt"), "new file\n");
    await git.add(["file.txt", "added.txt"]);
    await git.commit("feature work, not pushed");

    return { repoDir: workDir, remoteDir };
  }

  it("returns per-file patches for commits not yet pushed", async () => {
    const { repoDir: workDir, remoteDir } = await setupBranchWithCommits();
    repoDir = workDir;

    try {
      const patches = await getBranchDiffPatchesByPath(
        workDir,
        "main",
        "feature",
      );

      expect(patches.has("file.txt")).toBe(true);
      expect(patches.has("added.txt")).toBe(true);
      expect(patches.get("file.txt")).toContain("-line2");
      expect(patches.get("file.txt")).toContain("+changed");
      expect(patches.get("added.txt")).toContain("+new file");
    } finally {
      await rm(remoteDir, { recursive: true, force: true });
    }
  });

  it("returns deletions keyed by their path", async () => {
    const { repoDir: workDir, remoteDir } = await setupBranchWithCommits();
    repoDir = workDir;

    try {
      const git = createGitClient(workDir);
      await unlink(path.join(workDir, "file.txt"));
      await git.add(["file.txt"]);
      await git.commit("delete file.txt");

      const patches = await getBranchDiffPatchesByPath(
        workDir,
        "main",
        "feature",
      );

      expect(patches.get("file.txt")).toContain("deleted file mode");
    } finally {
      await rm(remoteDir, { recursive: true, force: true });
    }
  });
});

// Picked to land well past the default 64KB highWaterMark of
// `createReadStream` so the regression test actually exercises the
// across-chunk path of the streaming line counter.
const LINE_COUNT_LARGER_THAN_READ_STREAM_CHUNK = 800_000;

describe("getChangedFilesDetailed > untracked line counts", () => {
  let repoDir: string;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
      repoDir = "";
    }
  });

  it.each([
    { name: "trailing newline", content: "a\nb\nc\n", expected: 3 },
    { name: "no trailing newline", content: "a\nb\nc", expected: 3 },
    { name: "single byte, no newline", content: "a", expected: 1 },
    { name: "lone newline", content: "\n", expected: 1 },
    { name: "consecutive newlines", content: "\n\n", expected: 2 },
    // CRLF: legacy `split("\n")` counted only `\n` separators, so
    // `"a\r\nb\r\n"` -> 2 lines. Byte-counter matches.
    { name: "CRLF endings", content: "a\r\nb\r\n", expected: 2 },
  ])("counts $name as $expected line(s)", async ({ content, expected }) => {
    repoDir = await setupRepo();
    await writeFile(path.join(repoDir, "f.txt"), content);

    const files = await getChangedFilesDetailed(repoDir);
    const f = files.find((file) => file.path === "f.txt");

    expect(f).toMatchObject({ status: "untracked", linesAdded: expected });
  });

  it("reports 0 lines for empty untracked files", async () => {
    repoDir = await setupRepo();
    await writeFile(path.join(repoDir, "empty.txt"), "");

    const files = await getChangedFilesDetailed(repoDir);
    const empty = files.find((f) => f.path === "empty.txt");

    expect(empty).toMatchObject({ status: "untracked", linesAdded: 0 });
  });

  // Regression guard for the OOM in #2218. Before the fix `countFileLines`
  // read each untracked file's full content into memory via
  // `fs.readFile(..., "utf-8")`, 16-way concurrent against every untracked
  // path returned by `streamGitStatus` (up to 50k). On a monorepo with
  // multi-MB build artifacts this exhausted the main-process V8 heap
  // (`16 * file_bytes * 2` for V8's UTF-16) and froze the renderer waiting
  // on the dead tRPC call. The fix stream-counts via `createReadStream`,
  // so peak per-stream memory is ~64KB regardless of file size — the
  // multi-MB case below would have OOM'd pre-fix and must still report an
  // accurate line count.
  it("stream-counts untracked files larger than the streaming chunk size", async () => {
    repoDir = await setupRepo();
    const content = "a\n".repeat(LINE_COUNT_LARGER_THAN_READ_STREAM_CHUNK);
    await writeFile(path.join(repoDir, "huge.txt"), content);

    const files = await getChangedFilesDetailed(repoDir);
    const huge = files.find((f) => f.path === "huge.txt");

    expect(huge).toMatchObject({
      status: "untracked",
      linesAdded: LINE_COUNT_LARGER_THAN_READ_STREAM_CHUNK,
    });
  });

  // Regression for #2983 follow-up: an untracked binary file (png, mp4, …)
  // must not have its newline bytes counted as added lines. Pre-fix this
  // surfaced as an inflated diff badge (e.g. +8147) after dropping in a
  // screenshot or screen recording.
  it.each([["shot.png"], ["clip.mp4"]])(
    "reports no line count for untracked binary file %s",
    async (name) => {
      repoDir = await setupRepo();
      // Content packed with newline bytes — what the line counter would have
      // tallied if it didn't skip binary files.
      await writeFile(path.join(repoDir, name), "\n".repeat(8147));

      const files = await getChangedFilesDetailed(repoDir);
      const binary = files.find((f) => f.path === name);

      expect(binary).toMatchObject({ status: "untracked" });
      expect(binary?.linesAdded).toBeUndefined();
      expect(binary?.linesRemoved).toBeUndefined();
    },
  );
});

describe("computeDiffStatsFromFiles", () => {
  it("excludes binary files from line totals but still counts them as changed", () => {
    const files: ChangedFileInfo[] = [
      {
        path: "src/app.ts",
        status: "modified",
        linesAdded: 10,
        linesRemoved: 4,
      },
      // Binary line counts are meaningless newline-byte tallies — exclude them.
      {
        path: "assets/shot.png",
        status: "untracked",
        linesAdded: 8147,
        linesRemoved: 0,
      },
      {
        path: "assets/clip.mp4",
        status: "untracked",
        linesAdded: 5000,
        linesRemoved: 0,
      },
    ];

    expect(computeDiffStatsFromFiles(files)).toEqual({
      filesChanged: 3,
      linesAdded: 10,
      linesRemoved: 4,
    });
  });
});

describe("getAllBranches", () => {
  let repoDir: string | undefined;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
      repoDir = undefined;
    }
  });

  async function setupRebaseConflict(dir: string): Promise<void> {
    const git = createGitClient(dir);
    await git.checkoutLocalBranch("feature");
    await writeFile(path.join(dir, "file.txt"), "feature change\n");
    await git.add(["file.txt"]);
    await git.commit("on feature");
    await git.checkout("main");
    await writeFile(path.join(dir, "file.txt"), "main change\n");
    await git.add(["file.txt"]);
    await git.commit("on main");
    await git.checkout("feature");
    try {
      await git.rebase(["main"]);
    } catch {
      // expected: rebase pauses on conflict, leaving HEAD on a pseudo-branch
    }
  }

  it("returns only real branches, not the rebase pseudo-branch", async () => {
    repoDir = await setupRepo("main");
    await setupRebaseConflict(repoDir);

    const branches = await getAllBranches(repoDir);
    expect(branches).toEqual(expect.arrayContaining(["main", "feature"]));
    expect(branches).not.toContain("(no");
    expect(branches.every((b) => !b.startsWith("("))).toBe(true);
  });
});

describe("getGitBusyState", () => {
  let repoDir: string | undefined;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
      repoDir = undefined;
    }
  });

  it("reports busy=false in a clean repo", async () => {
    repoDir = await setupRepo("main");
    expect(await getGitBusyState(repoDir)).toEqual({ busy: false });
  });

  it("detects an in-progress rebase", async () => {
    repoDir = await setupRepo("main");
    const git = createGitClient(repoDir);

    await git.checkoutLocalBranch("feature");
    await writeFile(path.join(repoDir, "file.txt"), "feature change\n");
    await git.add(["file.txt"]);
    await git.commit("on feature");

    await git.checkout("main");
    await writeFile(path.join(repoDir, "file.txt"), "main change\n");
    await git.add(["file.txt"]);
    await git.commit("on main");

    await git.checkout("feature");
    try {
      await git.rebase(["main"]);
    } catch {
      // expected: conflict
    }

    expect(await getGitBusyState(repoDir)).toEqual({
      busy: true,
      operation: "rebase",
    });
  });
});

describe("remoteBranchExists", () => {
  let repoDir: string;
  let remoteDir: string;

  beforeEach(async () => {
    remoteDir = await mkdtemp(path.join(tmpdir(), "posthog-code-bare-"));
    const remoteGit = createGitClient(remoteDir);
    await remoteGit.init(["--bare", "--initial-branch", "main"]);

    repoDir = await mkdtemp(path.join(tmpdir(), "posthog-code-queries-"));
    const git = createGitClient(repoDir);
    await git.init(["--initial-branch", "main"]);
    await git.addConfig("user.name", "Test");
    await git.addConfig("user.email", "test@example.com");
    await git.addConfig("commit.gpgsign", "false");
    await git.addRemote("origin", remoteDir);
    await writeFile(path.join(repoDir, "file.txt"), "content\n");
    await git.add(["file.txt"]);
    await git.commit("initial");
    await git.push(["origin", "main"]);

    await git.checkoutLocalBranch("remote-only");
    await writeFile(path.join(repoDir, "extra.txt"), "extra\n");
    await git.add(["extra.txt"]);
    await git.commit("extra");
    await git.push(["origin", "remote-only"]);
    await git.checkout("main");
  });

  afterEach(async () => {
    for (const d of [repoDir, remoteDir]) {
      await rm(d, { recursive: true, force: true });
    }
  });

  it.each([
    { branch: "main", expected: true },
    { branch: "remote-only", expected: true },
    { branch: "nonexistent", expected: false },
  ])("returns $expected for branch '$branch'", async ({ branch, expected }) => {
    expect(await remoteBranchExists(repoDir, branch)).toBe(expected);
  });

  it("returns false when the remote is unreachable", async () => {
    await createGitClient(repoDir).remote([
      "set-url",
      "origin",
      "/nonexistent/path/to/remote",
    ]);
    expect(await remoteBranchExists(repoDir, "main")).toBe(false);
  });
});

describe("anyBranchRefExists", () => {
  let repoDir: string;

  // Builds refs via plumbing (commit-tree + update-ref) so the fixture also
  // works in sandboxes where `git commit` is unavailable.
  beforeEach(async () => {
    repoDir = await mkdtemp(path.join(tmpdir(), "posthog-code-refs-"));
    const git = createGitClient(repoDir);
    await git.init(["--initial-branch", "main"]);
    await git.addConfig("user.name", "Test");
    await git.addConfig("user.email", "test@example.com");
    const tree = (
      await git.raw(["hash-object", "-w", "-t", "tree", devNull])
    ).trim();
    const sha = (await git.raw(["commit-tree", tree, "-m", "seed"])).trim();
    await git.raw(["update-ref", "refs/heads/feat/local", sha]);
    await git.raw(["update-ref", "refs/remotes/upstream/feat/remote", sha]);
    await git.raw(["update-ref", "refs/tags/feat/tag-only", sha]);
  });

  afterEach(async () => {
    await rm(repoDir, { recursive: true, force: true });
  });

  it.each([
    { branch: "feat/local", expected: true },
    { branch: "feat/remote", expected: true },
    { branch: "feat/gone", expected: false },
    // A tag with the name does not resurrect a deleted branch.
    { branch: "feat/tag-only", expected: false },
  ])("returns $expected for '$branch'", async ({ branch, expected }) => {
    expect(await anyBranchRefExists(repoDir, branch)).toBe(expected);
  });
});

describe("getLinkedWorktreeMainPath", () => {
  // The `.git` layouts are fabricated with plain fs (no git binary needed):
  // a linked worktree is just a `.git` *file* whose `gitdir:` line points at
  // `<main>/.git/worktrees/<name>`.
  let baseDir: string;
  let repoDir: string;
  let worktreeDir: string;

  beforeEach(async () => {
    baseDir = await mkdtemp(path.join(tmpdir(), "posthog-code-wt-"));
    repoDir = path.join(baseDir, "main-repo");
    worktreeDir = path.join(baseDir, "my-worktree");
    await mkdir(path.join(repoDir, ".git", "worktrees", "my-worktree"), {
      recursive: true,
    });
    await mkdir(worktreeDir, { recursive: true });
    await writeFile(
      path.join(worktreeDir, ".git"),
      `gitdir: ${path.join(repoDir, ".git", "worktrees", "my-worktree")}\n`,
    );
  });

  afterEach(async () => {
    await rm(baseDir, { recursive: true, force: true });
  });

  it("returns the main checkout path for a linked worktree", () => {
    expect(getLinkedWorktreeMainPath(worktreeDir)).toBe(repoDir);
  });

  it("resolves a relative gitdir against the worktree", async () => {
    await writeFile(
      path.join(worktreeDir, ".git"),
      "gitdir: ../main-repo/.git/worktrees/my-worktree\n",
    );
    expect(getLinkedWorktreeMainPath(worktreeDir)).toBe(repoDir);
  });

  it("returns null for the main checkout (.git is a directory)", () => {
    expect(getLinkedWorktreeMainPath(repoDir)).toBeNull();
  });

  it("returns null for a directory that is not a repository", () => {
    expect(getLinkedWorktreeMainPath(baseDir)).toBeNull();
  });

  it("returns null for a submodule-style .git file", async () => {
    await writeFile(
      path.join(worktreeDir, ".git"),
      "gitdir: ../main-repo/.git/modules/child\n",
    );
    expect(getLinkedWorktreeMainPath(worktreeDir)).toBeNull();
  });
});

describe("listAllFiles", () => {
  let repoDir: string;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
    }
  });

  it("combines tracked and untracked files uncapped by default", async () => {
    repoDir = await setupRepo();
    await writeFile(path.join(repoDir, "untracked.txt"), "content");

    const files = await listAllFiles(repoDir);

    expect(files.sort()).toEqual(["file.txt", "untracked.txt"]);
  });

  it("truncates to maxFiles", async () => {
    repoDir = await setupRepo();
    const git = createGitClient(repoDir);
    await writeFile(path.join(repoDir, "b.txt"), "content");
    await writeFile(path.join(repoDir, "c.txt"), "content");
    await git.add(["b.txt", "c.txt"]);
    await git.commit("add more files");

    const files = await listAllFiles(repoDir, { maxFiles: 2 });

    expect(files.length).toBe(2);
  });

  it("keeps tracked files over untracked ones when truncating", async () => {
    repoDir = await setupRepo();
    await writeFile(path.join(repoDir, "untracked.txt"), "content");

    const files = await listAllFiles(repoDir, { maxFiles: 1 });

    expect(files).toEqual(["file.txt"]);
  });

  it("returns tracked files when the untracked scan times out", async () => {
    repoDir = await setupRepo();
    await writeFile(path.join(repoDir, "untracked.txt"), "content");

    const files = await listAllFiles(repoDir, { timeoutMs: 0 });

    expect(files).toContain("file.txt");
  });
});

describe("addToLocalExclude", () => {
  let repoDir: string;

  afterEach(async () => {
    if (repoDir) {
      await rm(repoDir, { recursive: true, force: true });
    }
  });

  it("does not confuse a nested pattern with an exact pattern", async () => {
    repoDir = await setupRepo();
    const git = createGitClient(repoDir);
    const excludePath = path.resolve(
      repoDir,
      await git.revparse(["--git-path", "info/exclude"]),
    );
    await writeFile(excludePath, "**/.claude/worktrees/\n");

    await addToLocalExclude(repoDir, ".claude");

    expect(await readFile(excludePath, "utf-8")).toBe(
      "**/.claude/worktrees/\n.claude\n",
    );
  });
});
