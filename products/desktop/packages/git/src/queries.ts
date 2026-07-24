import { createReadStream, readFileSync, statSync } from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { isBinaryFile } from "@posthog/shared";
import type { CreateGitClientOptions } from "./client";
import { mapWithConcurrency } from "./concurrency";
import { getGitOperationManager } from "./operation-manager";
import { streamGitStatus } from "./status-stream";

export interface WorktreeListEntry {
  path: string;
  head: string;
  branch: string | null;
}

export interface AheadBehind {
  aheadOfRemote: number;
  behind: number;
}

export interface GitStatus {
  isClean: boolean;
  staged: string[];
  modified: string[];
  deleted: string[];
  untracked: string[];
  overflowedDirs?: string[];
  totalUntrackedSeen?: number;
  totalUntrackedTruncated?: boolean;
}

type GitLike = {
  raw: (args: string[]) => Promise<string>;
  revparse: (args: string[]) => Promise<string>;
};

export async function detectDefaultBranch(git: GitLike): Promise<string> {
  try {
    const remoteBranch = await git.raw([
      "symbolic-ref",
      "refs/remotes/origin/HEAD",
    ]);
    return remoteBranch.trim().replace("refs/remotes/origin/", "");
  } catch {
    // Check common default branch names
    for (const candidate of ["main", "master"]) {
      try {
        await git.revparse(["--verify", candidate]);
        return candidate;
      } catch {}
    }

    // Check git config init.defaultBranch (user's configured default)
    try {
      const configured = await git.raw(["config", "init.defaultBranch"]);
      const branch = configured.trim();
      if (branch) {
        try {
          await git.revparse(["--verify", branch]);
          return branch;
        } catch {}
      }
    } catch {}

    // Fall back to current branch (HEAD)
    try {
      const head = await git.raw(["rev-parse", "--abbrev-ref", "HEAD"]);
      const branch = head.trim();
      if (branch && branch !== "HEAD") {
        return branch;
      }
    } catch {}

    throw new Error("Cannot determine default branch");
  }
}

async function detectDefaultBranchWithFallback(git: GitLike): Promise<string> {
  try {
    return await detectDefaultBranch(git);
  } catch {
    // Last resort: use current branch or "main"
    try {
      const head = await git.raw(["rev-parse", "--abbrev-ref", "HEAD"]);
      const branch = head.trim();
      if (branch && branch !== "HEAD") {
        return branch;
      }
    } catch {}
    return "main";
  }
}

export async function getCurrentBranch(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string | null> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const branch = await git.revparse(["--abbrev-ref", "HEAD"]);
      return branch === "HEAD" ? null : branch;
    },
    { signal: options?.abortSignal },
  );
}

export async function getDefaultBranch(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string> {
  const manager = getGitOperationManager();
  return manager.executeRead(baseDir, detectDefaultBranch, {
    signal: options?.abortSignal,
  });
}

export async function getRemoteUrl(
  baseDir: string,
  remote = "origin",
  options?: CreateGitClientOptions,
): Promise<string | null> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const url = await git.remote(["get-url", remote]);
        return url || null;
      } catch {
        if (remote === "origin") {
          const remotes = await git.getRemotes(true);
          if (remotes.length > 0 && remotes[0].refs.fetch) {
            return remotes[0].refs.fetch;
          }
        }
        return null;
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function getStatus(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<GitStatus> {
  const status = await streamGitStatus(baseDir, {
    signal: options?.abortSignal,
  });
  return {
    isClean: status.isClean,
    staged: status.staged,
    modified: status.modified,
    deleted: status.deleted,
    untracked: status.untracked,
    overflowedDirs: status.overflowedDirs,
    totalUntrackedSeen: status.totalUntrackedSeen,
    totalUntrackedTruncated: status.totalUntrackedTruncated,
  };
}

export async function hasChanges(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const status = await git.status(["--untracked-files=normal"]);
      return !status.isClean();
    },
    { signal: options?.abortSignal },
  );
}

export async function getAheadBehind(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<AheadBehind | null> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const branchOutput = await git.revparse(["--abbrev-ref", "HEAD"]);
      const branch = branchOutput === "HEAD" ? null : branchOutput;
      if (!branch) return null;

      try {
        await git.raw(["rev-parse", "--abbrev-ref", `${branch}@{upstream}`]);
      } catch {
        return null;
      }

      const status = await git.status(["--untracked-files=no"]);
      return {
        aheadOfRemote: status.ahead,
        behind: status.behind,
      };
    },
    { signal: options?.abortSignal },
  );
}

export async function branchExists(
  baseDir: string,
  branchName: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        await git.revparse(["--verify", branchName]);
        return true;
      } catch {
        return false;
      }
    },
    { signal: options?.abortSignal },
  );
}

/**
 * True when the branch exists as a local branch or as a remote-tracking
 * ref on any remote. Unlike `branchExists`, a tag or raw commit-ish with
 * the same name does not count, and nothing reaches the network — a
 * remote branch only counts once it has been fetched.
 */
export async function anyBranchRefExists(
  baseDir: string,
  branchName: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const refs = await git.raw([
        "for-each-ref",
        "--count=1",
        "--format=%(refname)",
        `refs/heads/${branchName}`,
        `refs/remotes/*/${branchName}`,
      ]);
      return refs.trim().length > 0;
    },
    { signal: options?.abortSignal },
  );
}

/**
 * Checks whether a branch exists on the remote without fetching it.
 * Uses `git ls-remote --heads`, which is read-only and reaches the remote.
 */
export async function remoteBranchExists(
  baseDir: string,
  branchName: string,
  options?: CreateGitClientOptions & { remote?: string },
): Promise<boolean> {
  const manager = getGitOperationManager();
  const remote = options?.remote ?? "origin";
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        // `--` keeps a branch name beginning with `-` from being parsed as an option.
        const output = await git.raw([
          "ls-remote",
          "--heads",
          remote,
          "--",
          branchName,
        ]);
        const target = `refs/heads/${branchName}`;
        return output
          .split("\n")
          .some((line) => line.trim().endsWith(`\t${target}`));
      } catch {
        return false;
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function listWorktrees(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<WorktreeListEntry[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const output = await git.raw(["worktree", "list", "--porcelain"]);
      const worktrees: WorktreeListEntry[] = [];
      let current: Partial<WorktreeListEntry> = {};

      for (const line of output.split("\n")) {
        if (line.startsWith("worktree ")) {
          if (current.path) {
            worktrees.push(current as WorktreeListEntry);
          }
          current = { path: line.slice(9), branch: null };
        } else if (line.startsWith("HEAD ")) {
          current.head = line.slice(5);
        } else if (line.startsWith("branch ")) {
          current.branch = line.slice(7).replace("refs/heads/", "");
        } else if (line === "detached") {
          current.branch = null;
        }
      }

      if (current.path) {
        worktrees.push(current as WorktreeListEntry);
      }

      return worktrees;
    },
    { signal: options?.abortSignal },
  );
}

export async function getFileAtHead(
  baseDir: string,
  filePath: string,
  options?: CreateGitClientOptions,
): Promise<string | null> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        return await git.show([`HEAD:${filePath}`]);
      } catch {
        return null;
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function getHeadSha(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string> {
  const manager = getGitOperationManager();
  return manager.executeRead(baseDir, (git) => git.revparse(["HEAD"]), {
    signal: options?.abortSignal,
  });
}

export async function isDetachedHead(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const branch = await getCurrentBranch(baseDir, options);
  return branch === null;
}

export async function isGitRepository(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        await git.revparse(["--is-inside-work-tree"]);
        return true;
      } catch {
        return false;
      }
    },
    { signal: options?.abortSignal },
  );
}

/**
 * Detects whether `dirPath` is a linked git worktree (created with
 * `git worktree add`) and returns the root of the main checkout it belongs
 * to, or null when it isn't one. Works without spawning git: in a linked
 * worktree `.git` is a file containing `gitdir: <main>/.git/worktrees/<name>`,
 * while a main checkout has a `.git` directory.
 */
export function getLinkedWorktreeMainPath(dirPath: string): string | null {
  try {
    const dotGit = path.join(dirPath, ".git");
    if (!statSync(dotGit).isFile()) return null;
    const match = readFileSync(dotGit, "utf8").match(/^gitdir:\s*(.+?)\s*$/m);
    if (!match) return null;
    const gitDir = path.resolve(dirPath, match[1]);
    // Expect <main>/.git/worktrees/<name>; anything else (e.g. a submodule's
    // `.git` file pointing into the parent's modules dir) is not a worktree.
    const worktreesDir = path.dirname(gitDir);
    const dotGitDir = path.dirname(worktreesDir);
    if (
      path.basename(worktreesDir) !== "worktrees" ||
      path.basename(dotGitDir) !== ".git"
    ) {
      return null;
    }
    return path.dirname(dotGitDir);
  } catch {
    return null;
  }
}

export async function getChangedFiles(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<Set<string>> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const changedFiles = new Set<string>();

      try {
        const defaultBranch = await detectDefaultBranchWithFallback(git);
        const branchOutput = await git.revparse(["--abbrev-ref", "HEAD"]);
        const currentBranch = branchOutput === "HEAD" ? null : branchOutput;

        if (currentBranch && currentBranch !== defaultBranch) {
          try {
            const diffOutput = await git.diff([
              "--name-only",
              `${defaultBranch}...HEAD`,
            ]);
            for (const file of diffOutput.split("\n").filter(Boolean)) {
              changedFiles.add(file);
            }
          } catch {}
        }
      } catch {}

      try {
        const status = await streamGitStatus(baseDir, {
          signal: options?.abortSignal,
        });
        for (const file of [
          ...status.modified,
          ...status.created,
          ...status.deleted,
          ...status.untracked,
        ]) {
          changedFiles.add(file);
        }
      } catch {}

      return changedFiles;
    },
    { signal: options?.abortSignal },
  );
}

export async function getAllBranches(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        // Use `for-each-ref` rather than `branch --list` (via simple-git's
        // branchLocal()): during a rebase or cherry-pick git surfaces a
        // pseudo-branch like `(no branch, rebasing main)` which simple-git's
        // parser mistakenly returns as a branch named `(no`.
        const output = await git.raw([
          "for-each-ref",
          "--format=%(refname:short)",
          "refs/heads/",
        ]);
        return output.split("\n").filter(Boolean);
      } catch {
        return [];
      }
    },
    { signal: options?.abortSignal },
  );
}

export type GitBusyOperation = "rebase" | "merge" | "cherry-pick" | "revert";

export type GitBusyState =
  | { busy: false }
  | { busy: true; operation: GitBusyOperation };

export async function inspectGitBusyState(git: GitLike): Promise<GitBusyState> {
  const toplevel = (await git.raw(["rev-parse", "--show-toplevel"])).trim();

  const resolveGitPath = async (gitPath: string): Promise<string> => {
    const relative = (
      await git.raw(["rev-parse", "--git-path", gitPath])
    ).trim();
    return path.isAbsolute(relative)
      ? relative
      : path.resolve(toplevel, relative);
  };

  const pathExists = async (gitPath: string): Promise<boolean> => {
    const resolved = await resolveGitPath(gitPath);
    try {
      await fs.access(resolved);
      return true;
    } catch {
      return false;
    }
  };

  const dirExists = async (gitPath: string): Promise<boolean> => {
    const resolved = await resolveGitPath(gitPath);
    try {
      const stat = await fs.stat(resolved);
      return stat.isDirectory();
    } catch {
      return false;
    }
  };

  if ((await dirExists("rebase-merge")) || (await dirExists("rebase-apply"))) {
    return { busy: true, operation: "rebase" };
  }
  if (await pathExists("MERGE_HEAD")) {
    return { busy: true, operation: "merge" };
  }
  if (await pathExists("CHERRY_PICK_HEAD")) {
    return { busy: true, operation: "cherry-pick" };
  }
  if (await pathExists("REVERT_HEAD")) {
    return { busy: true, operation: "revert" };
  }
  return { busy: false };
}

export async function getGitBusyState(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<GitBusyState> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        return await inspectGitBusyState(git);
      } catch {
        return { busy: false };
      }
    },
    { signal: options?.abortSignal },
  );
}

export type GitFileStatus =
  | "modified"
  | "added"
  | "deleted"
  | "renamed"
  | "untracked";

export interface ChangedFileInfo {
  path: string;
  status: GitFileStatus;
  originalPath?: string;
  linesAdded?: number;
  linesRemoved?: number;
  staged?: boolean;
}

export interface GetChangedFilesDetailedOptions extends CreateGitClientOptions {
  excludePatterns?: string[];
}

function matchesExcludePattern(filePath: string, patterns: string[]): boolean {
  return patterns.some((pattern) => {
    if (pattern.startsWith("/")) {
      return (
        filePath === pattern.slice(1) ||
        filePath.startsWith(`${pattern.slice(1)}/`)
      );
    }
    return filePath === pattern || filePath.startsWith(`${pattern}/`);
  });
}

async function countFileLines(
  filePath: string,
  options?: { signal?: AbortSignal },
): Promise<number> {
  try {
    // `lstat` instead of `stat` so an untracked symlink (rare, but legal)
    // pointing at /dev/zero or a path outside the workdir doesn't stream
    // forever — symlinks fail `isFile()` and short-circuit to 0.
    const stat = await fs.lstat(filePath);
    if (!stat.isFile() || stat.size === 0) return 0;
    return await new Promise<number>((resolve) => {
      let newlines = 0;
      let lastByte = -1;
      const stream = createReadStream(filePath, { signal: options?.signal });
      stream.on("data", (rawChunk) => {
        // Node types stream chunks as `string | Buffer`; without an
        // `encoding` option `createReadStream` always emits `Buffer`,
        // so the cast is for the type checker, not the runtime.
        const chunk = rawChunk as Buffer;
        // Native `Buffer.indexOf` — ~10x faster than a per-byte JS loop
        // on multi-MB buffers, which is the workload this whole function
        // exists to handle.
        for (
          let idx = chunk.indexOf(0x0a);
          idx !== -1;
          idx = chunk.indexOf(0x0a, idx + 1)
        ) {
          newlines++;
        }
        if (chunk.length > 0) lastByte = chunk[chunk.length - 1];
      });
      stream.on("end", () => {
        // Guards against TOCTOU truncation between lstat and read —
        // size > 0 at stat time, zero bytes by the time we open.
        if (lastByte === -1) {
          resolve(0);
          return;
        }
        resolve(lastByte === 0x0a ? newlines : newlines + 1);
      });
      stream.on("error", (err) => {
        // Don't propagate — caller already treats any failure as 0 lines.
        // But log so the next time a "shows 0 lines" mystery shows up
        // there's a breadcrumb (the original OOM in #2218 hid behind the
        // same silent-zero return).
        console.warn(`countFileLines failed for ${filePath}:`, err);
        resolve(0);
      });
    });
  } catch {
    return 0;
  }
}

export async function getChangedFilesDetailed(
  baseDir: string,
  options?: GetChangedFilesDetailedOptions,
): Promise<ChangedFileInfo[]> {
  const { excludePatterns, ...gitOptions } = options ?? {};
  const manager = getGitOperationManager();

  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const [stagedSummary, unstagedSummary, status] = await Promise.all([
          git.diffSummary(["--cached", "-M", "HEAD"]),
          git.diffSummary(["-M"]),
          streamGitStatus(baseDir, { signal: gitOptions?.abortSignal }),
        ]);

        const deletedSet = new Set(status.deleted);
        const createdSet = new Set(status.created);

        const diffSeenPaths = new Set<string>();
        const excludedPaths = new Set<string>();
        const files: ChangedFileInfo[] = [];

        const pushDiffFile = (
          file: (typeof stagedSummary.files)[number],
          staged: boolean,
        ) => {
          if (
            excludePatterns &&
            matchesExcludePattern(file.file, excludePatterns)
          ) {
            excludedPaths.add(file.file);
            return;
          }
          const hasFrom = "from" in file && file.from;
          const isBinary = file.binary;
          files.push({
            path: file.file,
            status: hasFrom
              ? "renamed"
              : deletedSet.has(file.file)
                ? "deleted"
                : createdSet.has(file.file)
                  ? "added"
                  : "modified",
            originalPath: hasFrom ? (file.from as string) : undefined,
            linesAdded: isBinary
              ? undefined
              : (file as { insertions: number }).insertions,
            linesRemoved: isBinary
              ? undefined
              : (file as { deletions: number }).deletions,
            staged,
          });
          diffSeenPaths.add(file.file);
          if (hasFrom) diffSeenPaths.add(file.from as string);
        };

        for (const file of stagedSummary.files) {
          pushDiffFile(file, true);
        }
        for (const file of unstagedSummary.files) {
          pushDiffFile(file, false);
        }

        const untrackedToCount: string[] = [];
        for (const file of status.untracked) {
          if (diffSeenPaths.has(file) || excludedPaths.has(file)) continue;
          if (excludePatterns && matchesExcludePattern(file, excludePatterns)) {
            continue;
          }
          if (isBinaryFile(file)) {
            files.push({ path: file, status: "untracked" });
            continue;
          }
          untrackedToCount.push(file);
        }

        const untrackedLineCounts = await mapWithConcurrency(
          untrackedToCount,
          16,
          (file) =>
            countFileLines(path.join(baseDir, file), {
              signal: gitOptions?.abortSignal,
            }),
          { signal: gitOptions?.abortSignal },
        );
        for (let i = 0; i < untrackedToCount.length; i++) {
          files.push({
            path: untrackedToCount[i],
            status: "untracked",
            linesAdded: untrackedLineCounts[i],
            linesRemoved: 0,
          });
        }

        return files;
      } catch {
        return [];
      }
    },
    { signal: gitOptions?.abortSignal },
  );
}

export async function getChangedFilesBetweenBranches(
  baseDir: string,
  baseBranch: string,
  headBranch?: string,
  options?: GetChangedFilesDetailedOptions,
): Promise<ChangedFileInfo[]> {
  const { excludePatterns, ...gitOptions } = options ?? {};
  const manager = getGitOperationManager();

  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const from = `origin/${baseBranch}`;
        const to = headBranch ?? "HEAD";

        const [diffSummary, nameStatusOutput] = await Promise.all([
          git.diffSummary(["-M", `${from}...${to}`]),
          git.raw(["diff", "--name-status", "-M", `${from}...${to}`]),
        ]);

        const statusMap = new Map<string, GitFileStatus>();
        for (const line of nameStatusOutput.split("\n").filter(Boolean)) {
          const parts = line.split("\t");
          const code = parts[0];
          const filePath = parts.length === 3 ? parts[2] : parts[1];
          if (!filePath) continue;

          if (code?.startsWith("R")) {
            statusMap.set(filePath, "renamed");
          } else if (code === "A") {
            statusMap.set(filePath, "added");
          } else if (code === "D") {
            statusMap.set(filePath, "deleted");
          } else {
            statusMap.set(filePath, "modified");
          }
        }

        const files: ChangedFileInfo[] = [];
        for (const file of diffSummary.files) {
          if (
            excludePatterns &&
            matchesExcludePattern(file.file, excludePatterns)
          ) {
            continue;
          }

          const hasFrom = "from" in file && file.from;
          const isBinary = file.binary;

          files.push({
            path: file.file,
            status: statusMap.get(file.file) ?? "modified",
            originalPath: hasFrom ? (file.from as string) : undefined,
            linesAdded: isBinary
              ? undefined
              : (file as { insertions: number }).insertions,
            linesRemoved: isBinary
              ? undefined
              : (file as { deletions: number }).deletions,
          });
        }

        return files;
      } catch {
        return [];
      }
    },
    { signal: gitOptions?.abortSignal },
  );
}

/**
 * Splits a unified `git diff` string into per-file patches, keyed by the `b/`
 * (post-rename) path, which is the shape `ChangedFileInfo.path` uses. Each
 * returned patch string begins with its own `diff --git ...` header and is a
 * valid standalone unified diff.
 */
export function splitUnifiedDiffByFile(raw: string): Map<string, string> {
  const patches = new Map<string, string>();
  if (!raw) return patches;

  const headerRegex = /^diff --git a\/.+? b\/(.+)$/gm;
  const matches: Array<{ path: string; start: number }> = [];
  let match = headerRegex.exec(raw);
  while (match !== null) {
    matches.push({ path: match[1], start: match.index });
    match = headerRegex.exec(raw);
  }

  for (let i = 0; i < matches.length; i++) {
    const { path, start } = matches[i];
    const end = i + 1 < matches.length ? matches[i + 1].start : raw.length;
    patches.set(path, raw.slice(start, end));
  }
  return patches;
}

export async function getBranchDiffPatchesByPath(
  baseDir: string,
  baseBranch: string,
  headBranch: string,
  options?: CreateGitClientOptions,
): Promise<Map<string, string>> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const raw = await git.diff([
          "-M",
          "--patch",
          "--no-color",
          `origin/${baseBranch}...${headBranch}`,
        ]);
        return splitUnifiedDiffByFile(raw);
      } catch {
        return new Map<string, string>();
      }
    },
    { signal: options?.abortSignal },
  );
}

export interface DiffStats {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
}

export interface GetDiffStatsOptions extends CreateGitClientOptions {
  excludePatterns?: string[];
}

export function computeDiffStatsFromFiles(files: ChangedFileInfo[]): DiffStats {
  let linesAdded = 0;
  let linesRemoved = 0;
  const uniquePaths = new Set<string>();

  for (const file of files) {
    uniquePaths.add(file.path);
    if (isBinaryFile(file.path)) continue;
    linesAdded += file.linesAdded ?? 0;
    linesRemoved += file.linesRemoved ?? 0;
  }

  return {
    filesChanged: uniquePaths.size,
    linesAdded,
    linesRemoved,
  };
}

export async function getDiffStats(
  baseDir: string,
  options?: GetDiffStatsOptions,
): Promise<DiffStats> {
  const files = await getChangedFilesDetailed(baseDir, options);
  return computeDiffStatsFromFiles(files);
}

export interface SyncStatus {
  aheadOfRemote: number;
  behind: number;
  aheadOfDefault: number;
  hasRemote: boolean;
  currentBranch: string | null;
  isFeatureBranch: boolean;
}

export async function getSyncStatus(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<SyncStatus> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const status = await git.status(["--untracked-files=no"]);
        const isDetached = status.detached || status.current === "HEAD";
        const currentBranch = isDetached ? null : status.current || null;

        if (!currentBranch) {
          return {
            aheadOfRemote: 0,
            behind: 0,
            aheadOfDefault: 0,
            hasRemote: false,
            currentBranch: null,
            isFeatureBranch: false,
          };
        }

        const defaultBranch = await detectDefaultBranchWithFallback(git);
        const hasRemote = status.tracking !== null;
        const isFeatureBranch = currentBranch !== defaultBranch;

        let aheadOfDefault = 0;
        if (isFeatureBranch) {
          try {
            const log = await git.log({
              from: `origin/${defaultBranch}`,
              to: currentBranch,
            });
            aheadOfDefault = log.total;
          } catch {}
        }

        return {
          aheadOfRemote: status.ahead,
          behind: status.behind,
          aheadOfDefault,
          hasRemote,
          currentBranch,
          isFeatureBranch,
        };
      } catch {
        return {
          aheadOfRemote: 0,
          behind: 0,
          aheadOfDefault: 0,
          hasRemote: false,
          currentBranch: null,
          isFeatureBranch: false,
        };
      }
    },
    { signal: options?.abortSignal },
  );
}

export interface CommitInfo {
  sha: string;
  shortSha: string;
  message: string;
  author: string;
  date: string;
}

export async function getLatestCommit(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<CommitInfo | null> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const log = await git.log({ maxCount: 1 });
        const latest = log.latest;
        if (!latest) return null;

        return {
          sha: latest.hash,
          shortSha: latest.hash.slice(0, 7),
          message: latest.message,
          author: latest.author_name,
          date: latest.date,
        };
      } catch {
        return null;
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function getCommitsBetweenBranches(
  baseDir: string,
  baseBranch: string,
  headBranch?: string,
  maxCount = 50,
  options?: CreateGitClientOptions,
): Promise<CommitInfo[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const log = await git.log({
          from: `origin/${baseBranch}`,
          to: headBranch ?? "HEAD",
          maxCount,
        });
        return log.all.map((c) => ({
          sha: c.hash,
          shortSha: c.hash.slice(0, 7),
          message: c.message,
          author: c.author_name,
          date: c.date,
        }));
      } catch {
        return [];
      }
    },
    { signal: options?.abortSignal },
  );
}

export interface CommitConventions {
  conventionalCommits: boolean;
  commonPrefixes: string[];
  sampleMessages: string[];
}

export async function getCommitConventions(
  baseDir: string,
  sampleSize = 20,
  options?: CreateGitClientOptions,
): Promise<CommitConventions> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const log = await git.log({ maxCount: sampleSize });
        const messages = log.all.map((c) => c.message);

        const conventionalPattern =
          /^(feat|fix|docs|style|refactor|test|chore|build|ci|perf|revert)(\(.+\))?:/;
        const conventionalCount = messages.filter((m) =>
          conventionalPattern.test(m),
        ).length;
        const conventionalCommits = conventionalCount > messages.length * 0.5;

        const prefixes = messages
          .map((m) => m.match(/^([a-z]+)(\(.+\))?:/)?.[1])
          .filter((p): p is string => Boolean(p));
        const prefixCounts = prefixes.reduce(
          (acc, p) => {
            acc[p] = (acc[p] || 0) + 1;
            return acc;
          },
          {} as Record<string, number>,
        );
        const commonPrefixes = Object.entries(prefixCounts)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5)
          .map(([prefix]) => prefix);

        return {
          conventionalCommits,
          commonPrefixes,
          sampleMessages: messages.slice(0, 5),
        };
      } catch {
        return {
          conventionalCommits: false,
          commonPrefixes: [],
          sampleMessages: [],
        };
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function fetch(
  baseDir: string,
  remote = "origin",
  options?: CreateGitClientOptions,
): Promise<void> {
  const manager = getGitOperationManager();
  await manager.executeWrite(
    baseDir,
    async (git) => {
      await git.fetch(remote);
    },
    { signal: options?.abortSignal },
  );
}

export async function hasRef(git: GitLike, ref: string): Promise<boolean> {
  try {
    await git.revparse(["--verify", "--quiet", `${ref}^{commit}`]);
    return true;
  } catch {
    return false;
  }
}

export async function fetchRef(
  git: GitLike,
  remote: string,
  ref: string,
  options?: { onError?: (message: string) => void },
): Promise<boolean> {
  try {
    // `--` keeps a ref beginning with `-` from being parsed as an option.
    await git.raw(["fetch", "--quiet", "--no-tags", remote, "--", ref]);
    return true;
  } catch (error) {
    options?.onError?.(error instanceof Error ? error.message : String(error));
    return false;
  }
}

export async function listFiles(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const output = await git.raw(["ls-files"]);
      return output.split("\n").filter(Boolean);
    },
    { signal: options?.abortSignal },
  );
}

export async function listUntrackedFiles(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const output = await git.raw([
        "ls-files",
        "--others",
        "--exclude-standard",
      ]);
      return output.split("\n").filter(Boolean);
    },
    { signal: options?.abortSignal },
  );
}

export interface ListAllFilesOptions {
  maxFiles?: number;
  timeoutMs?: number;
}

export async function listAllFiles(
  baseDir: string,
  options?: ListAllFilesOptions,
): Promise<string[]> {
  const { maxFiles, timeoutMs } = options ?? {};
  const controller =
    timeoutMs !== undefined ? new AbortController() : undefined;
  const timer =
    controller && timeoutMs !== undefined
      ? setTimeout(() => controller.abort(), timeoutMs)
      : undefined;
  try {
    const [tracked, untracked] = await Promise.all([
      listFiles(baseDir).catch((): string[] => []),
      listUntrackedFiles(baseDir, { abortSignal: controller?.signal }).catch(
        (): string[] => [],
      ),
    ]);
    const combined = tracked.concat(untracked);
    if (maxFiles !== undefined && combined.length > maxFiles) {
      combined.splice(maxFiles);
    }
    return combined;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// Tracked + untracked files containing `pattern` (literal, case-insensitive).
// Skips binaries (`-I`). Empty array on no matches.
export async function listFilesContainingText(
  baseDir: string,
  pattern: string,
  options?: CreateGitClientOptions,
): Promise<string[]> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const output = await git.raw([
        "grep",
        "-l",
        "-i",
        "-I",
        "--untracked",
        "--no-color",
        "--fixed-strings",
        pattern,
      ]);
      return output.split("\n").filter(Boolean);
    },
    { signal: options?.abortSignal },
  );
}

export async function hasTrackedFiles(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const files = await listFiles(baseDir, options);
  return files.length > 0;
}

export async function getStagedDiff(
  baseDir: string,
  options?: CreateGitClientOptions & { ignoreWhitespace?: boolean },
): Promise<string> {
  const manager = getGitOperationManager();
  const args = ["--cached", "HEAD"];
  if (options?.ignoreWhitespace) args.push("-w");
  return manager.executeRead(baseDir, (git) => git.diff(args), {
    signal: options?.abortSignal,
  });
}

export async function getUnstagedDiff(
  baseDir: string,
  options?: CreateGitClientOptions & { ignoreWhitespace?: boolean },
): Promise<string> {
  const manager = getGitOperationManager();
  const args: string[] = [];
  if (options?.ignoreWhitespace) args.push("-w");
  return manager.executeRead(baseDir, (git) => git.diff(args), {
    signal: options?.abortSignal,
  });
}

export async function getDiffHead(
  baseDir: string,
  options?: CreateGitClientOptions & { ignoreWhitespace?: boolean },
): Promise<string> {
  const manager = getGitOperationManager();
  const args = ["HEAD"];
  if (options?.ignoreWhitespace) args.push("--ignore-all-space");
  return manager.executeRead(baseDir, (git) => git.diff(args), {
    signal: options?.abortSignal,
  });
}

export async function stageFiles(
  baseDir: string,
  paths: string[],
  options?: CreateGitClientOptions,
): Promise<void> {
  const manager = getGitOperationManager();
  await manager.executeWrite(baseDir, (git) => git.add(paths), {
    signal: options?.abortSignal,
  });
}

export async function unstageFiles(
  baseDir: string,
  paths: string[],
  options?: CreateGitClientOptions,
): Promise<void> {
  const manager = getGitOperationManager();
  await manager.executeWrite(
    baseDir,
    (git) => git.reset(["HEAD", "--", ...paths]),
    { signal: options?.abortSignal },
  );
}

export async function getDiffAgainstRemote(
  baseDir: string,
  baseBranch: string,
  options?: CreateGitClientOptions,
): Promise<string> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    (git) => git.diff([`origin/${baseBranch}...HEAD`]),
    { signal: options?.abortSignal },
  );
}

export async function isCommitOnRemote(
  baseDir: string,
  commit: string,
  options?: CreateGitClientOptions,
): Promise<boolean> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      try {
        const output = await git.branch(["-r", "--contains", commit]);
        return output.all.length > 0;
      } catch {
        return false;
      }
    },
    { signal: options?.abortSignal },
  );
}

export async function resolveGitDir(
  baseDir: string,
  options?: CreateGitClientOptions,
): Promise<string> {
  const manager = getGitOperationManager();
  return manager.executeRead(
    baseDir,
    async (git) => {
      const gitDir = await git.revparse(["--git-dir"]);
      return path.resolve(baseDir, gitDir);
    },
    { signal: options?.abortSignal },
  );
}

export async function addToLocalExclude(
  baseDir: string,
  pattern: string,
  options?: CreateGitClientOptions,
): Promise<void> {
  const manager = getGitOperationManager();
  const excludePath = await manager.executeRead(
    baseDir,
    async (git) => {
      // --git-path resolves to the correct location for both regular repos
      // and worktrees (where info/exclude is shared via the common dir)
      const rel = await git.revparse(["--git-path", "info/exclude"]);
      return path.resolve(baseDir, rel);
    },
    { signal: options?.abortSignal },
  );

  let content = "";
  try {
    content = await fs.readFile(excludePath, "utf-8");
  } catch {}

  const normalizePattern = (value: string): string =>
    value.startsWith("/") ? value.slice(1) : value;
  const normalizedPattern = normalizePattern(pattern);
  const existingPatterns = content
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith("#"))
    .map(normalizePattern);
  if (existingPatterns.includes(normalizedPattern)) {
    return;
  }

  const infoDir = path.dirname(excludePath);
  await fs.mkdir(infoDir, { recursive: true });

  const newContent = content.trimEnd()
    ? `${content.trimEnd()}\n${pattern}\n`
    : `${pattern}\n`;
  await fs.writeFile(excludePath, newContent);
}
