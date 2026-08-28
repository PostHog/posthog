import { type ChildProcess, execFile, spawn } from "node:child_process";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { SagaLogger } from "@posthog/shared";
import {
  matchesExcludePatterns,
  parseExcludePatterns,
} from "./exclude-patterns";
import { getCleanEnv, getGitOperationManager } from "./operation-manager";
import {
  addToLocalExclude,
  branchExists,
  fetchRef,
  getDefaultBranch,
  getHeadSha,
  hasRef,
  listWorktrees as listWorktreesRaw,
} from "./queries";
import { clonePath, forceRemove, safeSymlink } from "./utils";
import { generateHumanReadableName } from "./worktree-name";

export interface WorktreeInfo {
  worktreePath: string;
  worktreeName: string;
  branchName: string;
  baseBranch: string;
  createdAt: string;
  output?: string;
}

export interface WorktreeConfig {
  mainRepoPath: string;
  worktreeBasePath?: string;
  logger?: SagaLogger;
}

const noopLogger: SagaLogger = {
  info: () => {},
  debug: () => {},
  warn: () => {},
  error: () => {},
};

const WORKTREE_FOLDER_NAME = ".posthog-code";

const WORKTREE_ADD_TIMEOUT_MS = 120_000;
const POST_CHECKOUT_HOOK_TIMEOUT_MS = 300_000;
const GIT_FETCH_TIMEOUT_MS = 120_000;
export const KILL_GRACE_MS = 5_000;

export function armProcessTimeout(
  proc: ChildProcess,
  timeoutMs: number,
): { timedOut: () => boolean; clear: () => void } {
  let timedOut = false;
  let hardKillTimer: NodeJS.Timeout | undefined;
  const timer = setTimeout(() => {
    timedOut = true;
    proc.kill("SIGTERM");
    hardKillTimer = setTimeout(() => proc.kill("SIGKILL"), KILL_GRACE_MS);
    hardKillTimer.unref();
  }, timeoutMs);
  timer.unref();
  return {
    timedOut: () => timedOut,
    clear: () => {
      clearTimeout(timer);
      if (hardKillTimer) {
        clearTimeout(hardKillTimer);
      }
    },
  };
}

export class WorktreeManager {
  private mainRepoPath: string;
  private worktreeBasePath: string | null;
  private repoName: string;
  private log: SagaLogger;

  constructor(config: WorktreeConfig) {
    this.mainRepoPath = config.mainRepoPath;
    this.worktreeBasePath = config.worktreeBasePath ?? null;
    this.repoName = path.basename(config.mainRepoPath);
    this.log = config.logger ?? noopLogger;
  }

  private usesExternalPath(): boolean {
    return this.worktreeBasePath !== null;
  }

  generateWorktreeName(): string {
    return generateHumanReadableName();
  }

  private getWorktreeBaseFolderPath(): string {
    if (this.worktreeBasePath) {
      return this.worktreeBasePath;
    }
    return path.join(this.mainRepoPath, WORKTREE_FOLDER_NAME);
  }

  private getWorktreePath(name: string): string {
    return path.join(this.getWorktreeBaseFolderPath(), name, this.repoName);
  }

  getLocalWorktreePath(): string {
    return path.join(this.getWorktreeBaseFolderPath(), "local", this.repoName);
  }

  async localWorktreeExists(): Promise<boolean> {
    const localPath = this.getLocalWorktreePath();
    try {
      await fs.access(localPath);
      return true;
    } catch {
      return false;
    }
  }

  async worktreeExists(name: string): Promise<boolean> {
    const worktreePath = this.getWorktreePath(name);
    try {
      await fs.access(worktreePath);
      return true;
    } catch {
      return false;
    }
  }

  async ensureArrayDirIgnored(): Promise<void> {
    const excludePath = path.join(this.mainRepoPath, ".git", "info", "exclude");
    const ignorePattern = `/${WORKTREE_FOLDER_NAME}/`;

    let content = "";
    try {
      content = await fs.readFile(excludePath, "utf-8");
    } catch {}

    if (
      content.includes(`/${WORKTREE_FOLDER_NAME}/`) ||
      content.includes(`/${WORKTREE_FOLDER_NAME}`)
    ) {
      return;
    }

    const infoDir = path.join(this.mainRepoPath, ".git", "info");
    await fs.mkdir(infoDir, { recursive: true });

    const newContent = `${content.trimEnd()}\n\n# PostHog worktrees\n${ignorePattern}\n`;
    await fs.writeFile(excludePath, newContent);
  }

  private async generateUniqueWorktreeName(): Promise<string> {
    let name = this.generateWorktreeName();
    let attempts = 0;
    const maxAttempts = 100;

    while ((await this.worktreeExists(name)) && attempts < maxAttempts) {
      name = this.generateWorktreeName();
      attempts++;
    }

    if (attempts >= maxAttempts) {
      name = `${this.generateWorktreeName()}${Date.now()}`;
    }

    return name;
  }

  async createWorktree(options?: {
    baseBranch?: string;
    onOutput?: (data: string) => void;
    /** Base the worktree on `origin/<baseBranch>` after fetching; falls back to the local ref if the fetch fails. */
    fetchBeforeCreate?: boolean;
  }): Promise<WorktreeInfo> {
    this.log.info("createWorktree started", {
      mainRepoPath: this.mainRepoPath,
      baseBranch: options?.baseBranch ?? null,
      fetchBeforeCreate: options?.fetchBeforeCreate ?? false,
    });

    const setupPromises: Promise<unknown>[] = [];

    if (!this.usesExternalPath()) {
      setupPromises.push(this.ensureArrayDirIgnored());
    }

    const worktreeNamePromise = this.generateUniqueWorktreeName();
    setupPromises.push(worktreeNamePromise);

    const baseBranchPromise = options?.baseBranch
      ? Promise.resolve(options.baseBranch)
      : getDefaultBranch(this.mainRepoPath);
    setupPromises.push(baseBranchPromise);

    await Promise.all(setupPromises);

    const worktreeName = await worktreeNamePromise;
    const baseBranch = await baseBranchPromise;
    const worktreePath = this.getWorktreePath(worktreeName);

    const parentDir = path.dirname(worktreePath);
    await fs.mkdir(parentDir, { recursive: true });

    const targetPath = this.usesExternalPath()
      ? worktreePath
      : `./${WORKTREE_FOLDER_NAME}/${worktreeName}/${this.repoName}`;

    const baseRef = options?.fetchBeforeCreate
      ? await this.resolveFreshBaseRef(baseBranch, options?.onOutput)
      : baseBranch;

    this.log.info("Resolved worktree target", {
      worktreeName,
      worktreePath,
      baseRef,
    });
    options?.onOutput?.(`Creating worktree from ${baseRef}...\n`);
    const output = await this.runWorktreeAdd(
      ["--detach", targetPath, baseRef],
      options?.onOutput,
    );

    await this.finalizeWorktree(worktreePath, options?.onOutput);

    return {
      worktreePath,
      worktreeName,
      branchName: "",
      baseBranch,
      createdAt: new Date().toISOString(),
      output: output.trim() || undefined,
    };
  }

  async createWorktreeForExistingBranch(
    branch: string,
    preferredName?: string,
    options?: { onOutput?: (data: string) => void },
  ): Promise<WorktreeInfo> {
    this.log.info("createWorktreeForExistingBranch started", {
      mainRepoPath: this.mainRepoPath,
      branch,
      preferredName: preferredName ?? null,
    });

    const exists = await branchExists(this.mainRepoPath, branch);
    if (!exists) {
      throw new Error(`Branch '${branch}' does not exist`);
    }

    const worktreeName = await this.resolveAvailableWorktreeName(preferredName);
    const { worktreePath, targetPath } =
      await this.prepareWorktreePath(worktreeName);

    this.log.info("Resolved worktree target", {
      worktreeName,
      worktreePath,
      branch,
    });
    const output = await this.runWorktreeAdd(
      [targetPath, branch],
      options?.onOutput,
    );

    await this.finalizeWorktree(worktreePath, options?.onOutput);

    return {
      worktreePath,
      worktreeName,
      branchName: branch,
      baseBranch: branch,
      createdAt: new Date().toISOString(),
      output: output.trim() || undefined,
    };
  }

  /**
   * Fetches a branch that exists on the remote but not locally, then creates a
   * worktree with a new local branch tracking `origin/<branch>`. Used when the
   * user opts in to checking out a remote-only branch (e.g. a contributor's PR).
   */
  async createWorktreeForRemoteBranch(
    branch: string,
    preferredName?: string,
    options?: { onOutput?: (data: string) => void; remote?: string },
  ): Promise<WorktreeInfo> {
    const remote = options?.remote ?? "origin";
    const remoteRef = `${remote}/${branch}`;

    this.log.info("createWorktreeForRemoteBranch started", {
      mainRepoPath: this.mainRepoPath,
      branch,
      remote,
      preferredName: preferredName ?? null,
    });

    options?.onOutput?.(`Fetching ${remoteRef}...\n`);
    const fetched = await this.fetchRefWithTimeout(remote, branch);
    if (!fetched) {
      throw new Error(`Failed to fetch branch '${branch}' from ${remote}`);
    }

    // Verify the remote-tracking ref was created. Restricted refspecs can cause
    // git fetch to succeed (updating only FETCH_HEAD) without writing
    // refs/remotes/<remote>/<branch>, which makes the subsequent worktree add
    // fail with an opaque "invalid reference" error. Check the fully-qualified
    // ref so a stray local branch/tag named `<remote>/<branch>` can't satisfy it.
    const trackingRefCreated = await branchExists(
      this.mainRepoPath,
      `refs/remotes/${remoteRef}`,
    );
    if (!trackingRefCreated) {
      throw new Error(
        `Fetch succeeded but remote-tracking ref '${remoteRef}' was not created. Check the remote's fetch refspec configuration.`,
      );
    }

    const worktreeName = await this.resolveAvailableWorktreeName(preferredName);
    const { worktreePath, targetPath } =
      await this.prepareWorktreePath(worktreeName);

    this.log.info("Resolved worktree target", {
      worktreeName,
      worktreePath,
      remoteRef,
    });
    // `-b <branch> <remoteRef>` creates a local branch at the fetched remote ref
    // and sets it up to track the remote branch.
    const output = await this.runWorktreeAdd(
      ["-b", branch, targetPath, remoteRef],
      options?.onOutput,
    );

    await this.finalizeWorktree(worktreePath, options?.onOutput);

    return {
      worktreePath,
      worktreeName,
      branchName: branch,
      baseBranch: remoteRef,
      createdAt: new Date().toISOString(),
      output: output.trim() || undefined,
    };
  }

  /**
   * Resolves a worktree name that does not collide with an existing worktree,
   * falling back to a freshly generated unique name when the preferred (or
   * default) name is already registered or present on disk.
   */
  private async resolveAvailableWorktreeName(
    preferredName?: string,
  ): Promise<string> {
    let worktreeName = preferredName ?? this.generateWorktreeName();

    if (preferredName) {
      const worktreePath = this.getWorktreePath(preferredName);
      const existingWorktrees = await this.listWorktrees();
      const isRegistered = existingWorktrees.some(
        (wt) => wt.worktreePath === worktreePath,
      );
      const existsOnDisk = await this.worktreeExists(preferredName);

      if (isRegistered || existsOnDisk) {
        worktreeName = `${this.generateWorktreeName()}${Date.now()}`;
        this.log.warn("Preferred worktree name unavailable, generated new", {
          preferredName,
          isRegistered,
          existsOnDisk,
          worktreeName,
        });
      }
    } else if (await this.worktreeExists(worktreeName)) {
      worktreeName = `${this.generateWorktreeName()}${Date.now()}`;
    }

    return worktreeName;
  }

  /**
   * Ensures the worktree's parent directory exists and computes the path passed
   * to `git worktree add`. For in-array worktrees it also makes sure the array
   * directory is gitignored. Returns the absolute worktree path and the
   * (possibly relative) target path the git command should use.
   */
  private async prepareWorktreePath(
    worktreeName: string,
  ): Promise<{ worktreePath: string; targetPath: string }> {
    if (!this.usesExternalPath()) {
      await this.ensureArrayDirIgnored();
    }

    const worktreePath = this.getWorktreePath(worktreeName);
    await fs.mkdir(path.dirname(worktreePath), { recursive: true });

    const targetPath = this.usesExternalPath()
      ? worktreePath
      : `./${WORKTREE_FOLDER_NAME}/${worktreeName}/${this.repoName}`;

    return { worktreePath, targetPath };
  }

  /**
   * Runs the post-create steps shared by every worktree: link local Claude
   * instructions, then process the worktree link/include files and the
   * post-checkout hook.
   */
  private async finalizeWorktree(
    worktreePath: string,
    onOutput?: (data: string) => void,
  ): Promise<void> {
    this.log.info("Finalizing worktree", { worktreePath });
    await this.symlinkClaudeLocalInstructions(worktreePath);
    const linkWarnings = await processWorktreeLink(
      this.mainRepoPath,
      worktreePath,
      { onOutput },
    );
    const includeWarnings = await processWorktreeInclude(
      this.mainRepoPath,
      worktreePath,
      { onOutput },
    );
    for (const warning of [...linkWarnings, ...includeWarnings]) {
      this.log.warn("Worktree setup warning", { worktreePath, ...warning });
    }
    const hookWarning = await runPostCheckoutHook(
      this.mainRepoPath,
      worktreePath,
      { onOutput },
    );
    if (hookWarning) {
      this.log.warn("post-checkout hook failed", {
        worktreePath,
        ...hookWarning,
      });
    }
    this.log.info("Worktree finalized", { worktreePath });
  }

  async createDetachedWorktreeAtCommit(
    commit: string,
    preferredName?: string,
    options?: { onOutput?: (data: string) => void },
  ): Promise<WorktreeInfo> {
    this.log.info("createDetachedWorktreeAtCommit started", {
      mainRepoPath: this.mainRepoPath,
      commit,
      preferredName: preferredName ?? null,
    });

    const worktreeName = await this.resolveAvailableWorktreeName(preferredName);
    const { worktreePath, targetPath } =
      await this.prepareWorktreePath(worktreeName);

    this.log.info("Resolved worktree target", {
      worktreeName,
      worktreePath,
      commit,
    });
    const output = await this.runWorktreeAdd(
      ["--detach", targetPath, commit],
      options?.onOutput,
    );

    await this.finalizeWorktree(worktreePath, options?.onOutput);

    return {
      worktreePath,
      worktreeName,
      branchName: "",
      baseBranch: commit,
      createdAt: new Date().toISOString(),
      output: output.trim() || undefined,
    };
  }

  /**
   * Returns `origin/<baseBranch>` after fetching, or the local branch name as a fallback.
   * Bases off `origin/<branch>` rather than fast-forwarding so local refs stay untouched.
   */
  private async resolveFreshBaseRef(
    baseBranch: string,
    onOutput?: (data: string) => void,
  ): Promise<string> {
    const manager = getGitOperationManager();
    const remote = "origin";
    const remoteRef = `${remote}/${baseBranch}`;

    onOutput?.(`Fetching ${remoteRef}...\n`);
    const fetched = await this.fetchRefWithTimeout(remote, baseBranch);

    if (!fetched) {
      this.log.warn("Fetch failed, falling back to local ref", {
        remoteRef,
        baseBranch,
      });
      onOutput?.(
        `Fetch failed for ${remoteRef}, falling back to local ${baseBranch}.\n`,
      );
      return baseBranch;
    }

    const remoteRefExists = await manager.executeRead(
      this.mainRepoPath,
      (git) => hasRef(git, remoteRef),
    );
    if (!remoteRefExists) {
      this.log.warn("Remote ref missing after fetch, falling back to local", {
        remoteRef,
        baseBranch,
      });
      onOutput?.(
        `Remote ref ${remoteRef} not found after fetch, falling back to local ${baseBranch}.\n`,
      );
      return baseBranch;
    }

    return remoteRef;
  }

  /**
   * Runs `git fetch <remote> <ref>` under the write lock with a hard timeout.
   * The fetch (unlike `git worktree add`) runs through simple-git, so it can't
   * use `armProcessTimeout`; instead we abort via the AbortSignal that
   * `executeWrite` forwards to its scoped git client, which kills the fetch
   * subprocess and releases the write lock. A blocked fetch (network stall,
   * unreachable remote) would otherwise hold the lock forever and strand every
   * later worktree creation for the repo. Returns false on failure or timeout
   * so callers degrade gracefully rather than hang.
   */
  private async fetchRefWithTimeout(
    remote: string,
    ref: string,
  ): Promise<boolean> {
    const manager = getGitOperationManager();
    const controller = new AbortController();
    const timer = setTimeout(() => {
      this.log.warn("git fetch timed out, aborting", {
        remote,
        ref,
        timeoutMs: GIT_FETCH_TIMEOUT_MS,
      });
      controller.abort();
    }, GIT_FETCH_TIMEOUT_MS);
    try {
      return await manager.executeWrite(
        this.mainRepoPath,
        (git) =>
          fetchRef(git, remote, ref, {
            onError: (message) =>
              this.log.warn("git fetch failed", {
                remote,
                ref,
                error: message,
              }),
          }),
        { signal: controller.signal },
      );
    } finally {
      clearTimeout(timer);
    }
  }

  // The repo write lock has no timeout; log both sides of the wait so a create that queues forever is visible.
  private async runWorktreeAdd(
    args: string[],
    onOutput?: (data: string) => void,
  ): Promise<string> {
    const manager = getGitOperationManager();
    this.log.info("Waiting for repo write lock", {
      mainRepoPath: this.mainRepoPath,
    });
    return manager.executeWrite(this.mainRepoPath, async () => {
      this.log.info("Repo write lock acquired", {
        mainRepoPath: this.mainRepoPath,
      });
      return this.spawnWorktreeAdd(args, { onOutput });
    });
  }

  private spawnWorktreeAdd(
    args: string[],
    options?: { onOutput?: (data: string) => void },
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const chunks: string[] = [];
      const argv = [
        "-c",
        "core.hooksPath=/dev/null",
        "worktree",
        "add",
        ...args,
      ];
      this.log.info("Spawning git worktree add", {
        cwd: this.mainRepoPath,
        argv: argv.join(" "),
      });
      const startedAt = Date.now();
      const proc = spawn("git", argv, {
        cwd: this.mainRepoPath,
        stdio: ["ignore", "pipe", "pipe"],
        env: getCleanEnv(),
      });

      const handleData = (data: Buffer) => {
        const text = data.toString("utf-8");
        chunks.push(text);
        options?.onOutput?.(text);
      };

      proc.stdout.on("data", handleData);
      proc.stderr.on("data", handleData);

      const timeout = armProcessTimeout(proc, WORKTREE_ADD_TIMEOUT_MS);

      proc.on("error", (err) => {
        timeout.clear();
        this.log.error("git worktree add failed to spawn", {
          error: err.message,
        });
        reject(err);
      });
      proc.on("close", (code) => {
        timeout.clear();
        const durationMs = Date.now() - startedAt;
        if (timeout.timedOut()) {
          this.log.error("git worktree add timed out", {
            durationMs,
            output: chunks.join(""),
          });
          reject(
            new Error(
              `git worktree add timed out after ${WORKTREE_ADD_TIMEOUT_MS}ms`,
            ),
          );
          return;
        }
        if (code !== 0) {
          this.log.error("git worktree add failed", {
            code,
            durationMs,
            output: chunks.join(""),
          });
          reject(
            new Error(
              `git worktree add exited with code ${code}: ${chunks.join("")}`,
            ),
          );
          return;
        }
        this.log.info("git worktree add succeeded", { durationMs });
        resolve(chunks.join(""));
      });
    });
  }

  async deleteWorktree(worktreePath: string): Promise<void> {
    const manager = getGitOperationManager();
    const resolvedWorktreePath = path.resolve(worktreePath);
    const resolvedMainRepoPath = path.resolve(this.mainRepoPath);

    if (resolvedWorktreePath === resolvedMainRepoPath) {
      throw new Error("Cannot delete worktree: path matches main repo path");
    }

    if (
      resolvedMainRepoPath.startsWith(resolvedWorktreePath) &&
      resolvedMainRepoPath !== resolvedWorktreePath
    ) {
      throw new Error(
        "Cannot delete worktree: path is a parent of main repo path",
      );
    }

    try {
      const gitPath = path.join(resolvedWorktreePath, ".git");
      const stat = await fs.stat(gitPath);
      if (stat.isDirectory()) {
        throw new Error(
          "Cannot delete worktree: path appears to be a main repository (contains .git directory)",
        );
      }
    } catch (error) {
      if (
        error instanceof Error &&
        error.message.includes("Cannot delete worktree")
      ) {
        throw error;
      }
    }

    // Rename-to-trash and prune both run inside the write lock so the on-disk
    // move and the git metadata update are atomic: if prune can't run (e.g. a
    // persistent external index.lock) we roll the rename back rather than leave
    // the worktree gone from disk but still registered (which would strand the
    // branch). Only the slow recursive removal of the trashed copy happens
    // outside the lock.
    const trashedPath = await manager
      .executeWrite(this.mainRepoPath, async (git) => {
        const moved = await this.moveToTrash(resolvedWorktreePath);
        if (!moved) return null;
        try {
          await git.raw(["worktree", "prune"]);
          return moved;
        } catch (pruneError) {
          await fs.rename(moved, resolvedWorktreePath).catch(() => {});
          throw pruneError;
        }
      })
      // A null (rename couldn't happen) or a throw (prune failed, rename rolled
      // back) both fall through to the in-place remove below.
      .catch((error) => {
        this.log.warn("Trash-based worktree delete failed, removing in place", {
          worktreePath,
          error: error instanceof Error ? error.message : String(error),
        });
        return null;
      });

    if (trashedPath) {
      void forceRemove(trashedPath).catch(() => {});
    } else {
      await manager.executeWrite(this.mainRepoPath, async (git) => {
        try {
          await git.raw(["worktree", "remove", worktreePath, "--force"]);
        } catch (removeError) {
          this.log.warn("git worktree remove failed, force-removing", {
            worktreePath,
            error:
              removeError instanceof Error
                ? removeError.message
                : String(removeError),
          });
          await forceRemove(worktreePath);
          await git.raw(["worktree", "prune"]);
        }
      });
    }

    // Both branches leave the worktree's `<base>/<name>` parent empty; remove it
    // so a deleted worktree never leaves a stray directory behind (best-effort:
    // rmdir no-ops if it isn't empty).
    await fs.rmdir(path.dirname(resolvedWorktreePath)).catch(() => {});
  }

  private getTrashFolderPath(): string {
    return path.join(this.getWorktreeBaseFolderPath(), ".trash");
  }

  /**
   * Renames a worktree into the trash folder so callers get an instant delete;
   * the multi-gigabyte recursive removal then runs in the background (and
   * `sweepTrash` mops up anything left behind by a crash). Returns null when
   * the rename cannot work (path missing, or on a different volume), in which
   * case the caller falls back to removing in place. Call inside the repo write
   * lock so the move stays ordered with the follow-up `git worktree prune`.
   */
  private async moveToTrash(worktreePath: string): Promise<string | null> {
    const trashDir = this.getTrashFolderPath();
    const trashedPath = path.join(
      trashDir,
      `${path.basename(path.dirname(worktreePath))}-${Date.now()}`,
    );
    try {
      await fs.mkdir(trashDir, { recursive: true });
      await fs.rename(worktreePath, trashedPath);
      return trashedPath;
    } catch {
      return null;
    }
  }

  /** Removes trashed worktrees left behind by interrupted background deletes. */
  async sweepTrash(): Promise<void> {
    await forceRemove(this.getTrashFolderPath());
  }

  async getWorktreeInfo(worktreePath: string): Promise<WorktreeInfo | null> {
    try {
      const worktrees = await this.listWorktrees();
      return worktrees.find((w) => w.worktreePath === worktreePath) ?? null;
    } catch {
      return null;
    }
  }

  async listWorktrees(): Promise<WorktreeInfo[]> {
    try {
      const rawWorktrees = await listWorktreesRaw(this.mainRepoPath);
      const baseFolderPath = this.getWorktreeBaseFolderPath();

      return rawWorktrees
        .filter((wt) => {
          const isMainRepo =
            path.resolve(wt.path) === path.resolve(this.mainRepoPath);
          const isUnderBase = wt.path.startsWith(baseFolderPath);
          return wt.branch && !isMainRepo && isUnderBase;
        })
        .map((wt) => ({
          worktreePath: wt.path,
          worktreeName: path.basename(path.dirname(wt.path)),
          branchName: wt.branch as string,
          baseBranch: "",
          createdAt: "",
        }));
    } catch (error) {
      this.log.warn("git worktree list failed, returning empty list", {
        mainRepoPath: this.mainRepoPath,
        error: error instanceof Error ? error.message : String(error),
      });
      return [];
    }
  }

  private async symlinkClaudeLocalInstructions(
    worktreePath: string,
  ): Promise<void> {
    const sourceClaudeLocalMd = path.join(this.mainRepoPath, "CLAUDE.local.md");
    const targetClaudeLocalMd = path.join(worktreePath, "CLAUDE.local.md");

    const linkedFile = await safeSymlink(
      sourceClaudeLocalMd,
      targetClaudeLocalMd,
      "file",
    );
    if (linkedFile) {
      await addToLocalExclude(worktreePath, "CLAUDE.local.md");
    }
  }

  async cleanupOrphanedWorktrees(associatedWorktreePaths: string[]): Promise<{
    deleted: string[];
    errors: Array<{ path: string; error: string }>;
  }> {
    const allWorktrees = await this.listWorktrees();
    const deleted: string[] = [];
    const errors: Array<{ path: string; error: string }> = [];

    const associatedPathsSet = new Set(
      associatedWorktreePaths.map((p) => path.resolve(p)),
    );

    for (const worktree of allWorktrees) {
      const resolvedPath = path.resolve(worktree.worktreePath);

      if (!associatedPathsSet.has(resolvedPath)) {
        try {
          await this.deleteWorktree(worktree.worktreePath);
          deleted.push(worktree.worktreePath);
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : String(error);
          errors.push({
            path: worktree.worktreePath,
            error: errorMessage,
          });
        }
      }
    }

    return { deleted, errors };
  }
}

/**
 * get all gitignored paths matching patterns from an exclude file
 *
 * Fast path: list candidates with `--exclude-standard` (so git collapses
 * standard-ignored trees) and re-apply the exclude file's patterns in-process.
 * If that in-process matching ever throws, fall back to letting git do the
 * whole match itself (`--exclude-from` only) — slower and does not collapse
 * ignored trees, but it is git's own battle-tested ignore logic, so a bug in
 * the hand-rolled matcher degrades to correct-but-slower rather than failing
 * worktree setup or silently linking nothing.
 */
async function getIgnoredPathsFromExcludeFile(
  mainRepoPath: string,
  excludeFile: string,
): Promise<string[]> {
  let content: string;
  try {
    content = await fs.readFile(path.join(mainRepoPath, excludeFile), "utf-8");
  } catch {
    // No exclude file (the common case) — genuinely nothing to link/copy.
    return [];
  }

  try {
    const patterns = parseExcludePatterns(content);
    if (patterns.length === 0) return [];

    const candidates = await listExcludeCandidates(mainRepoPath, excludeFile);
    return candidates
      .filter((candidate) => matchesExcludePatterns(candidate, patterns))
      .map((candidate) => candidate.replace(/\/$/, ""));
  } catch {
    return listIgnoredPathsViaGit(mainRepoPath, excludeFile);
  }
}

/**
 * Fallback matcher: git's own ignore matching over the exclude file, without
 * `--exclude-standard`. This is the pre-fast-path behavior — correct but it
 * walks standard-ignored trees instead of collapsing them. Used only when the
 * in-process matcher throws.
 */
function listIgnoredPathsViaGit(
  mainRepoPath: string,
  excludeFile: string,
): Promise<string[]> {
  return new Promise((resolve) => {
    execFile(
      "git",
      [
        "ls-files",
        "--ignored",
        "--others",
        "--directory",
        `--exclude-from=${excludeFile}`,
      ],
      { cwd: mainRepoPath },
      (error, stdout) => {
        if (error || !stdout) {
          resolve([]);
          return;
        }
        resolve(
          stdout
            .trim()
            .split("\n")
            .filter((line) => line.length > 0)
            .map((line) => line.replace(/\/$/, "")),
        );
      },
    );
  });
}

/**
 * Candidate untracked paths for exclude-file matching. `--exclude-standard`
 * lets git collapse gitignored trees (node_modules et al) into a single entry
 * instead of recursing through them — on a large repo that turns a multi-second
 * walk into a sub-second one. The exclude file's own patterns are then
 * re-applied in-process, which also stops matches buried inside standard-
 * ignored directories (e.g. a stray .env deep in node_modules) from surfacing.
 */
function listExcludeCandidates(
  mainRepoPath: string,
  excludeFile: string,
): Promise<string[]> {
  return new Promise((resolve) => {
    execFile(
      "git",
      [
        "ls-files",
        "--ignored",
        "--others",
        "--directory",
        "--exclude-standard",
        `--exclude-from=${excludeFile}`,
      ],
      { cwd: mainRepoPath },
      (error, stdout) => {
        if (error || !stdout) {
          resolve([]);
          return;
        }
        resolve(
          stdout
            .trim()
            .split("\n")
            .filter((line) => line.length > 0),
        );
      },
    );
  });
}

export interface WorktreeSetupWarning {
  path: string;
  error: string;
}

/**
 * copy gitignored files to workspace, per .worktreeinclude
 */
export async function processWorktreeInclude(
  mainRepoPath: string,
  worktreePath: string,
  options?: { onOutput?: (data: string) => void },
): Promise<WorktreeSetupWarning[]> {
  const paths = await getIgnoredPathsFromExcludeFile(
    mainRepoPath,
    ".worktreeinclude",
  );
  if (paths.length === 0) return [];

  const warnings: WorktreeSetupWarning[] = [];

  for (const relativePath of paths) {
    const source = path.join(mainRepoPath, relativePath);
    const destination = path.join(worktreePath, relativePath);

    try {
      options?.onOutput?.(`Copying ${relativePath}...\n`);
      const copied = await clonePath(source, destination);
      if (copied) {
        await addToLocalExclude(worktreePath, relativePath);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      options?.onOutput?.(
        `Warning: failed to copy ${relativePath}: ${message}\n`,
      );
      warnings.push({
        path: relativePath,
        error: message,
      });
    }
  }

  return warnings;
}

/**
 * symlink gitignored paths into workspace, per .worktreelink
 */
export async function processWorktreeLink(
  mainRepoPath: string,
  worktreePath: string,
  options?: { onOutput?: (data: string) => void },
): Promise<WorktreeSetupWarning[]> {
  const paths = await getIgnoredPathsFromExcludeFile(
    mainRepoPath,
    ".worktreelink",
  );
  if (paths.length === 0) return [];

  const warnings: WorktreeSetupWarning[] = [];

  for (const relativePath of paths) {
    const source = path.join(mainRepoPath, relativePath);
    const destination = path.join(worktreePath, relativePath);

    try {
      const stat = await fs.stat(source);
      const type = stat.isDirectory() ? "dir" : "file";

      options?.onOutput?.(`Linking ${relativePath}...\n`);
      const linked = await safeSymlink(source, destination, type);
      if (linked) {
        await addToLocalExclude(worktreePath, relativePath);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      options?.onOutput?.(
        `Warning: failed to link ${relativePath}: ${message}\n`,
      );
      warnings.push({
        path: relativePath,
        error: message,
      });
    }
  }

  return warnings;
}

function findPostCheckoutHook(mainRepoPath: string): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      "git",
      ["rev-parse", "--git-path", "hooks/post-checkout"],
      { cwd: mainRepoPath },
      async (error, stdout) => {
        if (error || !stdout.trim()) {
          resolve(null);
          return;
        }
        const resolved = stdout.trim();
        const hookPath = path.isAbsolute(resolved)
          ? resolved
          : path.join(mainRepoPath, resolved);

        try {
          await fs.access(hookPath, fs.constants.X_OK);
          resolve(hookPath);
        } catch {
          resolve(null);
        }
      },
    );
  });
}

/**
 * run post-checkout hook in the worktree
 *
 * hooks are intentionally skipped during worktree creation to avoid
 * potentially wonky behavior
 */
export async function runPostCheckoutHook(
  mainRepoPath: string,
  worktreePath: string,
  options?: { onOutput?: (data: string) => void },
): Promise<WorktreeSetupWarning | null> {
  const hookPath = await findPostCheckoutHook(mainRepoPath);
  if (!hookPath) return null;

  options?.onOutput?.(`Running post-checkout hook...\n`);

  const head = await getHeadSha(worktreePath);
  const nullSha = "0000000000000000000000000000000000000000";

  return new Promise((resolve) => {
    const chunks: string[] = [];
    const shell = process.env.SHELL || "/bin/sh";
    const proc = spawn(shell, ["-lc", `${hookPath} ${nullSha} ${head} 1`], {
      cwd: worktreePath,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const handleData = (data: Buffer) => {
      const text = data.toString();
      chunks.push(text);
      options?.onOutput?.(text);
    };

    proc.stdout.on("data", handleData);
    proc.stderr.on("data", handleData);

    const timeout = armProcessTimeout(proc, POST_CHECKOUT_HOOK_TIMEOUT_MS);

    const warn = (error: string): WorktreeSetupWarning => {
      options?.onOutput?.(`Warning: ${error}\n`);
      return { path: hookPath, error };
    };

    proc.on("error", (err) => {
      timeout.clear();
      resolve(warn(`post-checkout hook failed to spawn: ${err.message}`));
    });
    proc.on("close", (code) => {
      timeout.clear();
      if (timeout.timedOut()) {
        resolve(
          warn(
            `post-checkout hook timed out after ${POST_CHECKOUT_HOOK_TIMEOUT_MS}ms`,
          ),
        );
        return;
      }
      if (code !== 0) {
        resolve(
          warn(
            `post-checkout hook exited with code ${code}: ${chunks.join("")}`.trim(),
          ),
        );
        return;
      }
      resolve(null);
    });
  });
}
