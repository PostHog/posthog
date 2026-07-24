import { createGitClient, type GitClient } from "./client";
import { removeLock, waitForUnlock } from "./lock-detector";
import { AsyncReaderWriterLock } from "./rw-lock";

/**
 * Returns process.env with Electron/Chromium variables cleaned so that
 * child processes spawned by git hooks (e.g. biome via lint-staged) don't
 * crash trying to initialise GPU subsystems.
 *
 * Releases before the node-shim removal put a `node` alias for the Electron
 * binary on agent PATHs, and stale copies can outlive an update. We strip
 * most ELECTRON_/CHROME_ vars but keep ELECTRON_RUN_AS_NODE=1 so a hook that
 * still resolves such an alias runs it as plain Node.js instead of booting
 * the desktop app (GPU init → SIGTRAP crash). Dropping the var entirely is
 * tracked in #3114.
 *
 * GIT_LFS_SKIP_SMUDGE=1 prevents the LFS filter from running during
 * checkout/clone/worktree operations. Users who don't have git-lfs
 * installed (but whose repo declares `filter=lfs` in .gitattributes)
 * would otherwise hit `git-lfs: command not found` and fail the op.
 * Pointer files are preserved; real LFS content can be fetched later
 * with `git lfs pull` if the user installs git-lfs.
 */
export function getCleanEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue;
    if (key === "ELECTRON_RUN_AS_NODE") continue;
    if (key.startsWith("ELECTRON_") || key.startsWith("CHROME_")) continue;
    env[key] = value;
  }
  env.ELECTRON_RUN_AS_NODE = "1";
  env.GIT_LFS_SKIP_SMUDGE = "1";
  return env;
}

interface RepoState {
  lock: AsyncReaderWriterLock;
  client: GitClient;
  lastAccess: number;
}

export interface ExecuteOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  waitForExternalLock?: boolean;
  /**
   * Extra env vars merged on top of `getCleanEnv()` for the spawned git
   * subprocess. Used to pass through SessionStart-hook env (e.g.
   * `SSH_AUTH_SOCK` re-pointed at Secretive) so commit signing works for
   * UI-triggered commits.
   */
  env?: Record<string, string>;
}

class GitOperationManagerImpl {
  private repoStates = new Map<string, RepoState>();
  private cleanupInterval: ReturnType<typeof setInterval> | null = null;
  private static readonly CLEANUP_INTERVAL_MS = 60000;
  private static readonly IDLE_TIMEOUT_MS = 300000;

  constructor() {
    this.cleanupInterval = setInterval(
      () => this.cleanupIdleRepos(),
      GitOperationManagerImpl.CLEANUP_INTERVAL_MS,
    );
  }

  private getRepoState(repoPath: string): RepoState {
    let state = this.repoStates.get(repoPath);
    if (!state) {
      state = {
        lock: new AsyncReaderWriterLock(),
        client: createGitClient(repoPath),
        lastAccess: Date.now(),
      };
      this.repoStates.set(repoPath, state);
    }
    state.lastAccess = Date.now();
    return state;
  }

  private cleanupIdleRepos(): void {
    const now = Date.now();
    for (const [repoPath, state] of this.repoStates) {
      if (now - state.lastAccess > GitOperationManagerImpl.IDLE_TIMEOUT_MS) {
        this.repoStates.delete(repoPath);
      }
    }
  }

  async executeRead<T>(
    repoPath: string,
    operation: (git: GitClient) => Promise<T>,
    options?: ExecuteOptions,
  ): Promise<T> {
    const state = this.getRepoState(repoPath);
    const env = {
      ...getCleanEnv(),
      GIT_OPTIONAL_LOCKS: "0",
      ...options?.env,
    };

    if (options?.signal) {
      const scopedGit = createGitClient(repoPath, {
        abortSignal: options.signal,
      });
      return operation(scopedGit.env(env));
    }

    return operation(state.client.env(env));
  }

  async executeWrite<T>(
    repoPath: string,
    operation: (git: GitClient) => Promise<T>,
    options?: ExecuteOptions,
  ): Promise<T> {
    const state = this.getRepoState(repoPath);

    if (options?.waitForExternalLock !== false) {
      const unlocked = await waitForUnlock(
        repoPath,
        options?.timeoutMs ?? 10000,
      );
      if (!unlocked) {
        throw new Error(`Git repository is locked: ${repoPath}`);
      }
    }

    const env = { ...getCleanEnv(), ...options?.env };

    await state.lock.acquireWrite();
    try {
      if (options?.signal) {
        const scopedGit = createGitClient(repoPath, {
          abortSignal: options.signal,
        });
        return await operation(scopedGit.env(env));
      }

      return await operation(state.client.env(env));
    } catch (error) {
      if (options?.signal?.aborted) {
        await removeLock(repoPath).catch(() => {});
      }
      throw error;
    } finally {
      state.lock.releaseWrite();
    }
  }

  destroy(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }
    this.repoStates.clear();
  }
}

let instance: GitOperationManagerImpl | null = null;

export function getGitOperationManager(): GitOperationManagerImpl {
  if (!instance) {
    instance = new GitOperationManagerImpl();
  }
  return instance;
}

export function resetGitOperationManager(): void {
  if (instance) {
    instance.destroy();
    instance = null;
  }
}

export type GitOperationManager = GitOperationManagerImpl;
