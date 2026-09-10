import { Saga, type SagaLogger } from "@posthog/shared";
import type {
  FocusResult,
  FocusSession,
  StashResult,
} from "@posthog/workspace-client/types";

type SessionContext = {
  type: "detached_head";
  branchName: string;
  isDetached: boolean;
};

export interface EnableFocusParams {
  mainRepoPath: string;
  worktreePath: string;
  branch: string;
}

export interface FocusControllerDeps {
  cancelSessionPrompt(
    sessionId: string,
    reason: "moving_to_worktree",
  ): Promise<void>;
  checkout(repoPath: string, branch: string): Promise<FocusResult>;
  cleanWorkingTree(repoPath: string): Promise<void>;
  deleteSession(mainRepoPath: string): Promise<void>;
  detachWorktree(worktreePath: string): Promise<FocusResult>;
  getCommitSha(repoPath: string): Promise<string>;
  getCurrentBranch(mainRepoPath: string): Promise<string | null>;
  getSession(mainRepoPath: string): Promise<FocusSession | null>;
  isDirty(repoPath: string): Promise<boolean>;
  listLocalTaskIds(mainRepoPath: string): Promise<string[]>;
  listSessionIds(taskId: string): Promise<string[]>;
  listWorktreeTaskIds(worktreePath: string): Promise<string[]>;
  notifySessionContext(
    sessionId: string,
    context: SessionContext,
  ): Promise<void>;
  reattachWorktree(worktreePath: string, branch: string): Promise<FocusResult>;
  saveSession(session: FocusSession): Promise<void>;
  stash(repoPath: string, message: string): Promise<StashResult>;
  stashApply(repoPath: string, stashRef: string): Promise<FocusResult>;
  startSync(mainRepoPath: string, worktreePath: string): Promise<void>;
  startWatchingMainRepo(mainRepoPath: string): Promise<void>;
  stopSync(): Promise<void>;
  stopWatchingMainRepo(): Promise<void>;
  toRelativeWorktreePath(
    absolutePath: string,
    mainRepoPath: string,
  ): Promise<string>;
  worktreeExistsAtPath(relativePath: string): Promise<boolean>;
}

export type FocusSagaResult = FocusResult & {
  session: FocusSession | null;
  wasSwap: boolean;
};

export type DisableFocusResult = FocusResult;

interface FocusEnableInput {
  mainRepoPath: string;
  worktreePath: string;
  branch: string;
  originalBranch: string;
}

interface FocusEnableOutput {
  mainStashRef: string | null;
  commitSha: string;
}

interface FocusOutput {
  session: FocusSession;
  wasSwap: boolean;
}

class AlreadyFocusedError extends Error {
  constructor() {
    super("Already focused on this worktree");
  }
}

function validateFocusOperation(
  currentBranch: string | null,
  targetBranch: string,
): string | null {
  if (!currentBranch) {
    return "Cannot focus: main repo is in detached HEAD state.";
  }
  if (currentBranch === targetBranch) {
    return `Cannot focus: already on branch "${targetBranch}".`;
  }
  return null;
}

class FocusEnableSaga extends Saga<FocusEnableInput, FocusEnableOutput> {
  readonly sagaName = "FocusEnableSaga";

  constructor(
    private readonly deps: FocusControllerDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(input: FocusEnableInput): Promise<FocusEnableOutput> {
    const { mainRepoPath, worktreePath, branch, originalBranch } = input;

    await this.readOnlyStep("interrupt_local_agents", async () => {
      const taskIds = await this.deps.listLocalTaskIds(mainRepoPath);
      for (const taskId of taskIds) {
        const sessionIds = await this.deps.listSessionIds(taskId);
        for (const sessionId of sessionIds) {
          void this.deps
            .cancelSessionPrompt(sessionId, "moving_to_worktree")
            .catch(() => {});
        }
      }
    });

    const mainStashRef = await this.step({
      name: "stash_dirty_changes",
      execute: async () => {
        const isDirty = await this.deps.isDirty(mainRepoPath);
        if (!isDirty) return null;

        const timestamp = new Date().toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        });
        const result = await this.deps.stash(
          mainRepoPath,
          `posthog-code: focusing ${branch} (${timestamp})`,
        );
        if (!result.success) {
          throw new Error(result.error ?? "Failed to stash");
        }
        return result.stashRef ?? null;
      },
      rollback: async (stashRef) => {
        if (!stashRef) return;
        await this.deps.stashApply(mainRepoPath, stashRef).catch(() => {});
      },
    });

    await this.step({
      name: "detach_worktree",
      execute: async () => {
        const result = await this.deps.detachWorktree(worktreePath);
        if (!result.success) {
          throw new Error(result.error ?? "Failed to detach worktree");
        }

        const taskIds = await this.deps.listWorktreeTaskIds(worktreePath);
        for (const taskId of taskIds) {
          const sessionIds = await this.deps.listSessionIds(taskId);
          for (const sessionId of sessionIds) {
            void this.deps
              .notifySessionContext(sessionId, {
                type: "detached_head",
                branchName: branch,
                isDetached: true,
              })
              .catch(() => {});
          }
        }
      },
      rollback: async () => {
        await this.deps.reattachWorktree(worktreePath, branch).catch(() => {});

        const taskIds = await this.deps.listWorktreeTaskIds(worktreePath);
        for (const taskId of taskIds) {
          const sessionIds = await this.deps.listSessionIds(taskId);
          for (const sessionId of sessionIds) {
            void this.deps
              .notifySessionContext(sessionId, {
                type: "detached_head",
                branchName: branch,
                isDetached: false,
              })
              .catch(() => {});
          }
        }
      },
    });

    await this.step({
      name: "checkout_branch",
      execute: async () => {
        const result = await this.deps.checkout(mainRepoPath, branch);
        if (!result.success) {
          const error = result.error ?? `Failed to checkout ${branch}`;
          if (/would be overwritten by checkout/i.test(error)) {
            throw new Error(
              `Can't switch to ${branch}: uncommitted changes would be overwritten. Commit or stash them first.`,
            );
          }
          throw new Error(error);
        }
      },
      rollback: async () => {
        await this.deps.checkout(mainRepoPath, originalBranch).catch(() => {});
      },
    });

    await this.step({
      name: "start_sync",
      execute: () => this.deps.startSync(mainRepoPath, worktreePath),
      rollback: () => this.deps.stopSync().catch(() => {}),
    });

    const commitSha = await this.readOnlyStep("get_commit_sha", () =>
      this.deps.getCommitSha(mainRepoPath),
    );

    await this.step({
      name: "save_session",
      execute: () =>
        this.deps.saveSession({
          mainRepoPath,
          worktreePath,
          branch,
          originalBranch,
          mainStashRef,
          commitSha,
        }),
      rollback: () => this.deps.deleteSession(mainRepoPath).catch(() => {}),
    });

    await this.step({
      name: "start_watching_main_repo",
      execute: () => this.deps.startWatchingMainRepo(mainRepoPath),
      rollback: () => this.deps.stopWatchingMainRepo().catch(() => {}),
    });

    return { mainStashRef, commitSha };
  }
}

class FocusDisableSaga extends Saga<
  FocusSession,
  { stashPopWarning?: string }
> {
  readonly sagaName = "FocusDisableSaga";

  constructor(
    private readonly deps: FocusControllerDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(
    input: FocusSession,
  ): Promise<{ stashPopWarning?: string }> {
    const { mainRepoPath, worktreePath, branch, originalBranch, mainStashRef } =
      input;

    await this.readOnlyStep("stop_watching_main_repo", () =>
      this.deps.stopWatchingMainRepo(),
    );

    await this.step({
      name: "stop_sync",
      execute: () => this.deps.stopSync(),
      rollback: () =>
        this.deps.startSync(mainRepoPath, worktreePath).catch(() => {}),
    });

    await this.readOnlyStep("clean_working_tree", () =>
      this.deps.cleanWorkingTree(mainRepoPath),
    );

    await this.step({
      name: "checkout_original_branch",
      execute: async () => {
        const result = await this.deps.checkout(mainRepoPath, originalBranch);
        if (!result.success) {
          throw new Error(result.error ?? "Failed to checkout original branch");
        }
      },
      rollback: async () => {
        await this.deps.checkout(mainRepoPath, branch).catch(() => {});
      },
    });

    await this.step({
      name: "reattach_worktree",
      execute: async () => {
        const result = await this.deps.reattachWorktree(worktreePath, branch);
        if (!result.success) {
          throw new Error(result.error ?? "Failed to reattach worktree");
        }

        const taskIds = await this.deps.listWorktreeTaskIds(worktreePath);
        for (const taskId of taskIds) {
          const sessionIds = await this.deps.listSessionIds(taskId);
          for (const sessionId of sessionIds) {
            void this.deps
              .notifySessionContext(sessionId, {
                type: "detached_head",
                branchName: branch,
                isDetached: false,
              })
              .catch(() => {});
          }
        }
      },
      rollback: async () => {
        await this.deps.detachWorktree(worktreePath).catch(() => {});
      },
    });

    let stashPopWarning: string | undefined;
    if (mainStashRef) {
      stashPopWarning = await this.readOnlyStep("restore_stash", async () => {
        const result = await this.deps.stashApply(mainRepoPath, mainStashRef);
        if (!result.success) {
          return `Stash apply failed: ${result.error}. Run 'git stash apply ${mainStashRef}' manually.`;
        }
        return undefined;
      });
    }

    await this.readOnlyStep("delete_session", () =>
      this.deps.deleteSession(mainRepoPath),
    );

    return { stashPopWarning };
  }
}

class FocusSaga extends Saga<
  EnableFocusParams & { currentSession: FocusSession | null },
  FocusOutput
> {
  readonly sagaName = "FocusSaga";

  constructor(
    private readonly deps: FocusControllerDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(
    input: EnableFocusParams & { currentSession: FocusSession | null },
  ): Promise<FocusOutput> {
    const { mainRepoPath, worktreePath, branch, currentSession } = input;

    const wasSwap = await this.readOnlyStep("check_swap", async () => {
      if (!currentSession || currentSession.mainRepoPath !== mainRepoPath) {
        return false;
      }
      if (currentSession.worktreePath === worktreePath) {
        throw new AlreadyFocusedError();
      }
      return true;
    });

    if (wasSwap && currentSession) {
      await this.step({
        name: "unfocus_current",
        execute: async () => {
          const result = await new FocusDisableSaga(this.deps, this.log).run(
            currentSession,
          );
          if (!result.success) {
            throw new Error(`Failed to unfocus: ${result.error}`);
          }
        },
        rollback: async () => {},
      });
    }

    const currentBranch = await this.readOnlyStep("get_current_branch", () =>
      this.deps.getCurrentBranch(mainRepoPath),
    );

    await this.readOnlyStep("validate", async () => {
      const error = validateFocusOperation(currentBranch, branch);
      if (error) {
        throw new Error(error);
      }
    });

    const enableResult = await this.step({
      name: "enable_focus",
      execute: async () => {
        const result = await new FocusEnableSaga(this.deps, this.log).run({
          mainRepoPath,
          worktreePath,
          branch,
          originalBranch: currentBranch as string,
        });
        if (!result.success) {
          throw new Error(result.error);
        }
        return result.data;
      },
      rollback: async () => {},
    });

    return {
      session: {
        mainRepoPath,
        worktreePath,
        branch,
        originalBranch: currentBranch as string,
        mainStashRef: enableResult.mainStashRef,
        commitSha: enableResult.commitSha,
      },
      wasSwap,
    };
  }
}

class FocusRestoreSaga extends Saga<
  { mainRepoPath: string },
  FocusSession | null
> {
  readonly sagaName = "FocusRestoreSaga";

  constructor(
    private readonly deps: FocusControllerDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(input: {
    mainRepoPath: string;
  }): Promise<FocusSession | null> {
    const { mainRepoPath } = input;

    const session = await this.readOnlyStep("get_session", () =>
      this.deps.getSession(mainRepoPath),
    );
    if (!session) {
      return null;
    }

    const relWorktreePath = await this.deps.toRelativeWorktreePath(
      session.worktreePath,
      mainRepoPath,
    );

    const validatedSession = await this.readOnlyStep(
      "validate_state",
      async (): Promise<FocusSession | null> => {
        if (session.originalBranch === session.branch) {
          await this.deps.deleteSession(mainRepoPath);
          return null;
        }

        const exists = await this.deps.worktreeExistsAtPath(relWorktreePath);
        if (!exists) {
          await this.deps.deleteSession(mainRepoPath);
          return null;
        }

        const currentBranch = await this.deps.getCurrentBranch(mainRepoPath);
        if (!currentBranch) {
          await this.deps.deleteSession(mainRepoPath);
          return null;
        }

        if (currentBranch !== session.branch) {
          const currentCommitSha = await this.deps.getCommitSha(mainRepoPath);
          if (currentCommitSha === session.commitSha) {
            const updatedSession: FocusSession = {
              ...session,
              branch: currentBranch,
            };
            await this.deps.saveSession(updatedSession);
            return updatedSession;
          }

          await this.deps.deleteSession(mainRepoPath);
          return null;
        }

        return session;
      },
    );

    if (!validatedSession) {
      return null;
    }

    // restore explicitly re-saves the validated session so the workspace-server
    // watcher has the current in-memory session before startWatchingMainRepo.
    await this.readOnlyStep("save_session", () =>
      this.deps.saveSession(validatedSession),
    );

    await this.readOnlyStep("start_sync", () =>
      this.deps.startSync(mainRepoPath, validatedSession.worktreePath),
    );

    await this.readOnlyStep("start_watching_main_repo", () =>
      this.deps.startWatchingMainRepo(mainRepoPath),
    );

    return validatedSession;
  }
}

export class FocusController {
  constructor(
    private readonly deps: FocusControllerDeps,
    private readonly logger?: SagaLogger,
  ) {}

  async enableFocus(
    params: EnableFocusParams,
    currentSession: FocusSession | null,
  ): Promise<FocusSagaResult> {
    const result = await new FocusSaga(this.deps, this.logger).run({
      ...params,
      currentSession,
    });

    if (!result.success) {
      if (
        result.error === "Already focused on this worktree" &&
        currentSession
      ) {
        return { success: true, session: currentSession, wasSwap: false };
      }

      return {
        success: false,
        error: result.error,
        session: null,
        wasSwap: false,
      };
    }

    return {
      success: true,
      session: result.data.session,
      wasSwap: result.data.wasSwap,
    };
  }

  async disableFocus(session: FocusSession): Promise<DisableFocusResult> {
    const result = await new FocusDisableSaga(this.deps, this.logger).run(
      session,
    );

    if (!result.success) {
      return { success: false, error: result.error };
    }

    return { success: true, stashPopWarning: result.data.stashPopWarning };
  }

  async restore(mainRepoPath: string): Promise<FocusSession | null> {
    const result = await new FocusRestoreSaga(this.deps, this.logger).run({
      mainRepoPath,
    });

    if (!result.success) {
      if (result.error === "Invalid focus state") {
        return null;
      }
      return null;
    }

    return result.data;
  }
}
