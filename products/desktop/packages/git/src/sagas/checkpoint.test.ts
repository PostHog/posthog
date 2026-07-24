import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { createGitClient } from "../client";
import {
  CaptureCheckpointSaga,
  DiffCheckpointSaga,
  deleteCheckpoint,
  getGitBusyState,
  listCheckpoints,
  RevertCheckpointSaga,
} from "./checkpoint";

async function setupRepo(): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "posthog-code-checkpoint-"));
  const git = createGitClient(dir);
  await git.init();
  await git.addConfig("user.name", "PostHog Code Test");
  await git.addConfig("user.email", "posthog-code-test@example.com");
  await git.addConfig("commit.gpgsign", "false");

  await writeFile(path.join(dir, "a.txt"), "one\n");
  await writeFile(path.join(dir, "b.txt"), "base\n");
  await git.add(["a.txt", "b.txt"]);
  await git.commit("initial");

  return dir;
}

async function withRepo<T>(fn: (repoPath: string) => Promise<T>): Promise<T> {
  const repoPath = await setupRepo();
  try {
    return await fn(repoPath);
  } finally {
    await rm(repoPath, { recursive: true, force: true });
  }
}

async function withRepoAndWorktree<T>(
  fn: (repoPath: string, worktreePath: string) => Promise<T>,
): Promise<T> {
  const repoPath = await setupRepo();
  const worktreePath = await mkdtemp(
    path.join(tmpdir(), "posthog-code-worktree-"),
  );
  try {
    const git = createGitClient(repoPath);
    await git.raw(["worktree", "add", worktreePath]);
    return await fn(repoPath, worktreePath);
  } finally {
    await rm(worktreePath, { recursive: true, force: true });
    await rm(repoPath, { recursive: true, force: true });
  }
}

async function getIndexFileContent(
  repoPath: string,
  filePath: string,
): Promise<string> {
  const git = createGitClient(repoPath);
  const output = await git.raw(["show", `:${filePath}`]);
  return output;
}

async function captureCheckpoint(
  repoPath: string,
  checkpointId: string,
): Promise<void> {
  const capture = new CaptureCheckpointSaga();
  const result = await capture.run({ baseDir: repoPath, checkpointId });
  expect(result.success).toBe(true);
}

async function revertCheckpoint(
  repoPath: string,
  checkpointId: string,
): Promise<void> {
  const revert = new RevertCheckpointSaga();
  const result = await revert.run({ baseDir: repoPath, checkpointId });
  expect(result.success).toBe(true);
}

describe("checkpoint sagas", () => {
  it("captures and reverts worktree + index + untracked", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);

      // staged change
      await writeFile(path.join(repoPath, "a.txt"), "staged\n");
      await git.add(["a.txt"]);

      // unstaged change
      await writeFile(path.join(repoPath, "b.txt"), "unstaged\n");

      // untracked
      await writeFile(path.join(repoPath, "c.txt"), "untracked\n");

      await captureCheckpoint(repoPath, "test-checkpoint");

      // mutate after capture
      await writeFile(path.join(repoPath, "a.txt"), "after\n");
      await git.add(["a.txt"]);
      await writeFile(path.join(repoPath, "b.txt"), "after-unstaged\n");
      await rm(path.join(repoPath, "c.txt"));
      await writeFile(path.join(repoPath, "d.txt"), "new-untracked\n");

      await revertCheckpoint(repoPath, "test-checkpoint");

      const aWorktree = await readFile(path.join(repoPath, "a.txt"), "utf8");
      const aIndex = await getIndexFileContent(repoPath, "a.txt");
      const bWorktree = await readFile(path.join(repoPath, "b.txt"), "utf8");
      const cWorktree = await readFile(path.join(repoPath, "c.txt"), "utf8");

      expect(aWorktree).toBe("staged\n");
      expect(aIndex).toBe("staged");
      expect(bWorktree).toBe("unstaged\n");
      expect(cWorktree).toBe("untracked\n");

      const status = await git.raw(["status", "--porcelain"]);
      const lines = status.trim().split("\n").filter(Boolean);
      expect(lines).toContain("M  a.txt");
      expect(lines).toContain(" M b.txt");
      expect(lines).toContain("?? c.txt");
      expect(lines).not.toContain("?? d.txt");
    });
  });

  it("restores renames, deletes, and nested untracked files", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);

      // staged rename
      await git.raw(["mv", "a.txt", "renamed.txt"]);

      // unstaged delete
      await rm(path.join(repoPath, "b.txt"));

      // nested untracked
      await mkdir(path.join(repoPath, "nested/dir"), { recursive: true });
      await writeFile(path.join(repoPath, "nested/dir/file.txt"), "nested\n");

      await captureCheckpoint(repoPath, "rename-delete");

      // mutate after capture
      await git.raw(["mv", "renamed.txt", "a.txt"]);
      await writeFile(path.join(repoPath, "b.txt"), "recreated\n");
      await rm(path.join(repoPath, "nested/dir/file.txt"));

      await revertCheckpoint(repoPath, "rename-delete");

      const renamed = await readFile(
        path.join(repoPath, "renamed.txt"),
        "utf8",
      );
      expect(renamed).toBe("one\n");
      await expect(
        readFile(path.join(repoPath, "a.txt"), "utf8"),
      ).rejects.toBeTruthy();
      await expect(
        readFile(path.join(repoPath, "b.txt"), "utf8"),
      ).rejects.toBeTruthy();
      const nested = await readFile(
        path.join(repoPath, "nested/dir/file.txt"),
        "utf8",
      );
      expect(nested).toBe("nested\n");
    });
  });

  it("round-trips binary content", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const binaryPath = path.join(repoPath, "bin.dat");
      const data = Buffer.from([0, 1, 2, 3, 255, 128, 64]);
      await writeFile(binaryPath, data);
      await git.add(["bin.dat"]);

      await captureCheckpoint(repoPath, "binary");

      await writeFile(binaryPath, Buffer.from([9, 9, 9]));

      await revertCheckpoint(repoPath, "binary");

      const restored = await readFile(binaryPath);
      expect(Buffer.compare(restored, data)).toBe(0);
    });
  });

  it("works on a detached HEAD", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      await writeFile(path.join(repoPath, "c.txt"), "second\n");
      await git.add(["c.txt"]);
      await git.commit("second");

      const head = (await git.revparse(["HEAD"])).trim();
      await git.checkout([`${head}^`]);
      const detachedHead = (await git.revparse(["HEAD"])).trim();

      await writeFile(path.join(repoPath, "a.txt"), "detached\n");

      await captureCheckpoint(repoPath, "detached");

      await writeFile(path.join(repoPath, "a.txt"), "after\n");

      await revertCheckpoint(repoPath, "detached");

      const restored = await readFile(path.join(repoPath, "a.txt"), "utf8");
      expect(restored).toBe("detached\n");
      const headAfter = (await git.revparse(["HEAD"])).trim();
      expect(headAfter).toBe(detachedHead);
    });
  });

  it("works in a worktree", async () => {
    await withRepoAndWorktree(async (_repoPath, worktreePath) => {
      const worktreeGit = createGitClient(worktreePath);
      await writeFile(path.join(worktreePath, "a.txt"), "wt-staged\n");
      await worktreeGit.add(["a.txt"]);
      await writeFile(path.join(worktreePath, "b.txt"), "wt-unstaged\n");
      await writeFile(path.join(worktreePath, "c.txt"), "wt-untracked\n");

      await captureCheckpoint(worktreePath, "worktree");

      await writeFile(path.join(worktreePath, "a.txt"), "after\n");
      await worktreeGit.add(["a.txt"]);
      await rm(path.join(worktreePath, "c.txt"));

      await revertCheckpoint(worktreePath, "worktree");

      const aWorktree = await readFile(
        path.join(worktreePath, "a.txt"),
        "utf8",
      );
      const aIndex = await getIndexFileContent(worktreePath, "a.txt");
      const bWorktree = await readFile(
        path.join(worktreePath, "b.txt"),
        "utf8",
      );
      const cWorktree = await readFile(
        path.join(worktreePath, "c.txt"),
        "utf8",
      );

      expect(aWorktree).toBe("wt-staged\n");
      expect(aIndex).toBe("wt-staged");
      expect(bWorktree).toBe("wt-unstaged\n");
      expect(cWorktree).toBe("wt-untracked\n");
    });
  });

  it("handles submodules without breaking", { timeout: 15000 }, async () => {
    const subRepo = await mkdtemp(
      path.join(tmpdir(), "posthog-code-submodule-"),
    );
    await withRepo(async (repoPath) => {
      const subGit = createGitClient(subRepo);
      await subGit.init();
      await subGit.addConfig("user.name", "PostHog Code Test");
      await subGit.addConfig("user.email", "posthog-code-test@example.com");
      await subGit.addConfig("commit.gpgsign", "false");
      await writeFile(path.join(subRepo, "sub.txt"), "sub\n");
      await subGit.add(["sub.txt"]);
      await subGit.commit("sub-init");

      const git = createGitClient(repoPath);
      await git
        .env({ ...process.env, GIT_ALLOW_PROTOCOL: "file" })
        .raw(["submodule", "add", subRepo, "submod"]);
      await git.commit("add submodule");

      await captureCheckpoint(repoPath, "submodule");

      await writeFile(path.join(repoPath, "a.txt"), "after\n");

      await revertCheckpoint(repoPath, "submodule");

      const subStatus = await git.raw(["submodule", "status"]);
      expect(subStatus.trim()).not.toBe("");
      const subExists = await readFile(
        path.join(repoPath, "submod/sub.txt"),
        "utf8",
      );
      expect(subExists).toBe("sub\n");
    });
    await rm(subRepo, { recursive: true, force: true });
  });

  it("fails capture with a clear error when index has unresolved merges", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const defaultBranch = (
        await git.raw(["rev-parse", "--abbrev-ref", "HEAD"])
      ).trim();

      await git.checkoutLocalBranch("feature");
      await writeFile(path.join(repoPath, "a.txt"), "feature\n");
      await git.add(["a.txt"]);
      await git.commit("feature-change");

      await git.checkout(defaultBranch);
      await writeFile(path.join(repoPath, "a.txt"), "default\n");
      await git.add(["a.txt"]);
      await git.commit("default-change");

      await git.raw(["merge", "feature"]);
      const status = await git.raw(["status", "--porcelain"]);
      expect(status.trim().split("\n")).toContain("UU a.txt");

      const capture = new CaptureCheckpointSaga();
      const result = await capture.run({
        baseDir: repoPath,
        checkpointId: "conflicted-index",
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error).toContain("git operation is in progress");
      expect(result.error).toContain("merge");
      expect(result.failedStep).toBe("check_git_busy");
    });
  });

  it("restores checkpoint on unborn HEAD", async () => {
    const repoPath = await mkdtemp(
      path.join(tmpdir(), "posthog-code-checkpoint-"),
    );
    try {
      const git = createGitClient(repoPath);
      await git.init();
      await git.addConfig("user.name", "PostHog Code Test");
      await git.addConfig("user.email", "posthog-code-test@example.com");

      await writeFile(path.join(repoPath, "x.txt"), "one\n");
      await captureCheckpoint(repoPath, "unborn-head");

      await writeFile(path.join(repoPath, "x.txt"), "two\n");
      await writeFile(path.join(repoPath, "y.txt"), "new\n");

      await revertCheckpoint(repoPath, "unborn-head");

      const restoredX = await readFile(path.join(repoPath, "x.txt"), "utf8");
      expect(restoredX).toBe("one\n");

      const status = await git.raw(["status", "--porcelain"]);
      expect(status.trim().split("\n").filter(Boolean).sort()).toEqual([
        "?? x.txt",
      ]);
    } finally {
      await rm(repoPath, { recursive: true, force: true });
    }
  });

  it("diffs between checkpoints and current", async () => {
    await withRepo(async (repoPath) => {
      await writeFile(path.join(repoPath, "a.txt"), "one\n");
      await captureCheckpoint(repoPath, "diff-1");

      await writeFile(path.join(repoPath, "a.txt"), "two\n");
      await captureCheckpoint(repoPath, "diff-2");

      const diffSaga = new DiffCheckpointSaga();
      const diffResult = await diffSaga.run({
        baseDir: repoPath,
        from: "diff-1",
        to: "diff-2",
      });
      expect(diffResult.success).toBe(true);
      if (!diffResult.success) return;
      expect(diffResult.data.diff).toContain("-one");
      expect(diffResult.data.diff).toContain("+two");
    });
  });

  it("diff against current excludes ignored-file changes", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      await writeFile(path.join(repoPath, ".gitignore"), "ignored.log\n");
      await git.add([".gitignore"]);
      await git.commit("add-ignore");

      await captureCheckpoint(repoPath, "ignore-diff");

      await writeFile(path.join(repoPath, "ignored.log"), "ignored-change\n");
      await writeFile(path.join(repoPath, "a.txt"), "tracked-change\n");

      const diffSaga = new DiffCheckpointSaga();
      const diffResult = await diffSaga.run({
        baseDir: repoPath,
        from: "ignore-diff",
        to: "current",
      });

      expect(diffResult.success).toBe(true);
      if (!diffResult.success) return;
      expect(diffResult.data.diff).toContain("a.txt");
      expect(diffResult.data.diff).not.toContain("ignored.log");
      expect(diffResult.data.diff).toContain("tracked-change");
    });
  });

  it("drops untracked files larger than the worktree size cap", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const largePath = path.join(repoPath, "large.bin");
      await writeFile(largePath, Buffer.alloc(1024 * 1024 + 1, 7));
      await writeFile(path.join(repoPath, "small.txt"), "tiny\n");

      await captureCheckpoint(repoPath, "large-untracked");

      await rm(largePath);
      await rm(path.join(repoPath, "small.txt"));

      await revertCheckpoint(repoPath, "large-untracked");

      await expect(readFile(largePath)).rejects.toBeTruthy();
      const small = await readFile(path.join(repoPath, "small.txt"), "utf8");
      expect(small).toBe("tiny\n");

      const status = await git.raw(["status", "--porcelain"]);
      expect(status).not.toContain("large.bin");
    });
  });

  it("preserves tracked files larger than the cap when content is unchanged", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const largePath = path.join(repoPath, "tracked-large.bin");
      const data = Buffer.alloc(1024 * 1024 + 1, 3);
      await writeFile(largePath, data);
      await git.add(["tracked-large.bin"]);
      await git.commit("add large tracked");

      await writeFile(path.join(repoPath, "a.txt"), "edited\n");

      await captureCheckpoint(repoPath, "large-tracked-unchanged");

      await writeFile(path.join(repoPath, "a.txt"), "after\n");
      await rm(largePath);

      await revertCheckpoint(repoPath, "large-tracked-unchanged");

      const a = await readFile(path.join(repoPath, "a.txt"), "utf8");
      expect(a).toBe("edited\n");
      const restored = await readFile(largePath);
      expect(Buffer.compare(restored, data)).toBe(0);
    });
  });

  it("rolls tracked large files back to HEAD when modified locally", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const largePath = path.join(repoPath, "tracked-large.bin");
      const original = Buffer.alloc(1024 * 1024 + 1, 1);
      await writeFile(largePath, original);
      await git.add(["tracked-large.bin"]);
      await git.commit("add large tracked");

      const modified = Buffer.alloc(1024 * 1024 + 1, 9);
      await writeFile(largePath, modified);

      await captureCheckpoint(repoPath, "large-tracked-modified");

      await writeFile(largePath, Buffer.alloc(1024 * 1024 + 1, 5));

      await revertCheckpoint(repoPath, "large-tracked-modified");

      const restored = await readFile(largePath);
      expect(Buffer.compare(restored, original)).toBe(0);
    });
  });

  it("does not leak temp index into normal git operations", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      await writeFile(path.join(repoPath, "a.txt"), "staged\n");
      await git.add(["a.txt"]);

      await captureCheckpoint(repoPath, "no-leak");

      const status = await git.raw(["status", "--porcelain"]);
      expect(status.trim().split("\n")).toContain("M  a.txt");
    });
  });

  it("fails capture during interactive rebase", async () => {
    const repoPath = await setupRepo();
    try {
      const git = createGitClient(repoPath);

      await writeFile(path.join(repoPath, "a.txt"), "second\n");
      await git.add(["a.txt"]);
      await git.commit("second");

      await writeFile(path.join(repoPath, "a.txt"), "third\n");
      await git.add(["a.txt"]);
      await git.commit("third");

      const rebaseMergeRelative = (
        await git.raw(["rev-parse", "--git-path", "rebase-merge"])
      ).trim();
      const rebaseMergePath = path.resolve(repoPath, rebaseMergeRelative);
      await mkdir(rebaseMergePath, { recursive: true });

      const busyState = await getGitBusyState(git);
      expect(busyState).toEqual({ busy: true, operation: "rebase" });

      const capture = new CaptureCheckpointSaga();
      const result = await capture.run({
        baseDir: repoPath,
        checkpointId: "during-rebase",
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error).toContain("git operation is in progress");
      expect(result.error).toContain("rebase");
      expect(result.failedStep).toBe("check_git_busy");
    } finally {
      await rm(repoPath, { recursive: true, force: true });
    }
  });

  it("fails capture during cherry-pick", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const defaultBranch = (
        await git.raw(["rev-parse", "--abbrev-ref", "HEAD"])
      ).trim();

      await git.checkoutLocalBranch("feature");
      await writeFile(path.join(repoPath, "a.txt"), "feature\n");
      await git.add(["a.txt"]);
      await git.commit("feature-change");
      const featureCommit = (await git.revparse(["HEAD"])).trim();

      await git.checkout(defaultBranch);
      await writeFile(path.join(repoPath, "a.txt"), "conflict\n");
      await git.add(["a.txt"]);
      await git.commit("conflict-change");

      try {
        await git.raw(["cherry-pick", featureCommit]);
      } catch {
        // expected to fail with conflict
      }

      const busyState = await getGitBusyState(git);
      expect(busyState).toEqual({ busy: true, operation: "cherry-pick" });

      const capture = new CaptureCheckpointSaga();
      const result = await capture.run({
        baseDir: repoPath,
        checkpointId: "during-cherry-pick",
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error).toContain("git operation is in progress");
      expect(result.error).toContain("cherry-pick");
    });
  });

  it("fails capture during revert", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);

      await writeFile(path.join(repoPath, "a.txt"), "second\n");
      await git.add(["a.txt"]);
      await git.commit("second");

      await writeFile(path.join(repoPath, "a.txt"), "third\n");
      await git.add(["a.txt"]);
      await git.commit("third");
      const thirdCommit = (await git.revparse(["HEAD"])).trim();

      await writeFile(path.join(repoPath, "a.txt"), "fourth\n");
      await git.add(["a.txt"]);
      await git.commit("fourth");

      try {
        await git.raw(["revert", "--no-commit", thirdCommit]);
      } catch {
        // expected to fail with conflict
      }

      const busyState = await getGitBusyState(git);
      expect(busyState).toEqual({ busy: true, operation: "revert" });

      const capture = new CaptureCheckpointSaga();
      const result = await capture.run({
        baseDir: repoPath,
        checkpointId: "during-revert",
      });

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error).toContain("git operation is in progress");
      expect(result.error).toContain("revert");
    });
  });

  it("returns clean state when no git operation in progress", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      const busyState = await getGitBusyState(git);
      expect(busyState).toEqual({ busy: false });
    });
  });

  it("lists checkpoints sorted by timestamp descending", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);

      await captureCheckpoint(repoPath, "first");
      await new Promise((r) => setTimeout(r, 10));
      await captureCheckpoint(repoPath, "second");
      await new Promise((r) => setTimeout(r, 10));
      await captureCheckpoint(repoPath, "third");

      const checkpoints = await listCheckpoints(git);
      expect(checkpoints).toHaveLength(3);
      expect(checkpoints[0].checkpointId).toBe("third");
      expect(checkpoints[1].checkpointId).toBe("second");
      expect(checkpoints[2].checkpointId).toBe("first");
    });
  });

  it("deletes a checkpoint", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);

      await captureCheckpoint(repoPath, "to-delete");
      let checkpoints = await listCheckpoints(git);
      expect(checkpoints).toHaveLength(1);

      await deleteCheckpoint(git, "to-delete");
      checkpoints = await listCheckpoints(git);
      expect(checkpoints).toHaveLength(0);
    });
  });

  it("throws when deleting non-existent checkpoint", async () => {
    await withRepo(async (repoPath) => {
      const git = createGitClient(repoPath);
      await expect(deleteCheckpoint(git, "does-not-exist")).rejects.toThrow(
        "Checkpoint not found",
      );
    });
  });
});
