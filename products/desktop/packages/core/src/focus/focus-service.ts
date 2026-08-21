import { TypedEventEmitter } from "@posthog/shared";
import type { FocusBranchRenamedEvent } from "@posthog/workspace-client/types";
import { inject, injectable } from "inversify";
import {
  FOCUS_SESSION_STORE,
  FOCUS_WORKSPACE_CLIENT,
  FOCUS_WORKTREE_PATHS,
  type FocusSessionStore,
  type FocusWorkspaceClient,
  type FocusWorktreePaths,
} from "./host-focus";
import {
  type FocusResult,
  FocusServiceEvent,
  type FocusServiceEvents,
  type FocusSession,
  type IFocusService,
  type StashResult,
} from "./identifiers";

@injectable()
export class FocusHostService
  extends TypedEventEmitter<FocusServiceEvents>
  implements IFocusService
{
  constructor(
    @inject(FOCUS_WORKSPACE_CLIENT)
    private readonly workspaceClient: FocusWorkspaceClient,
    @inject(FOCUS_SESSION_STORE)
    private readonly store: FocusSessionStore,
    @inject(FOCUS_WORKTREE_PATHS)
    private readonly paths: FocusWorktreePaths,
  ) {
    super();
    this.focus.onBranchRenamed.subscribe(undefined, {
      onData: (event) => {
        void this.handleBranchRenamed(event);
      },
      onError: () => {},
    });
    this.focus.onForeignBranchCheckout.subscribe(undefined, {
      onData: (event) => {
        this.emit(FocusServiceEvent.ForeignBranchCheckout, event);
      },
      onError: () => {},
    });
  }

  private get focus() {
    return this.workspaceClient.focus;
  }

  getSession(mainRepoPath: string): FocusSession | null {
    return this.store.getSession(mainRepoPath);
  }

  async saveSession(session: FocusSession): Promise<void> {
    this.store.saveSession(session);
    await this.focus.saveSession.mutate(session);
  }

  async deleteSession(mainRepoPath: string): Promise<void> {
    this.store.deleteSession(mainRepoPath);
    await this.focus.deleteSession.mutate({ mainRepoPath });
  }

  isFocusActive(mainRepoPath: string): boolean {
    return this.getSession(mainRepoPath) !== null;
  }

  validateFocusOperation(
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

  async getCommitSha(repoPath: string): Promise<string> {
    return await this.focus.getCommitSha.query({ repoPath });
  }

  async findWorktreeByBranch(
    mainRepoPath: string,
    branch: string,
  ): Promise<string | null> {
    return await this.focus.findWorktreeByBranch.query({
      mainRepoPath,
      branch,
    });
  }

  toRelativeWorktreePath(absolutePath: string, mainRepoPath: string): string {
    return this.paths.toRelativeWorktreePath(absolutePath, mainRepoPath);
  }

  toAbsoluteWorktreePath(relativePath: string): string {
    return this.paths.toAbsoluteWorktreePath(relativePath);
  }

  async worktreeExistsAtPath(relativePath: string): Promise<boolean> {
    return await this.paths.worktreeExistsAtPath(relativePath);
  }

  async cleanWorkingTree(repoPath: string): Promise<void> {
    await this.focus.cleanWorkingTree.mutate({ repoPath });
  }

  async detachWorktree(worktreePath: string): Promise<FocusResult> {
    return await this.focus.detachWorktree.mutate({ worktreePath });
  }

  async reattachWorktree(
    worktreePath: string,
    branchName: string,
  ): Promise<FocusResult> {
    return await this.focus.reattachWorktree.mutate({
      worktreePath,
      branch: branchName,
    });
  }

  async isDirty(repoPath: string): Promise<boolean> {
    return await this.focus.isDirty.query({ repoPath });
  }

  async stash(repoPath: string, message: string): Promise<StashResult> {
    return await this.focus.stash.mutate({ repoPath, message });
  }

  async stashApply(repoPath: string, stashRef: string): Promise<FocusResult> {
    return await this.focus.stashApply.mutate({ repoPath, stashRef });
  }

  async stashPop(repoPath: string): Promise<FocusResult> {
    return await this.focus.stashPop.mutate({ repoPath });
  }

  async checkout(repoPath: string, branch: string): Promise<FocusResult> {
    return await this.focus.checkout.mutate({ repoPath, branch });
  }

  async startSync(mainRepoPath: string, worktreePath: string): Promise<void> {
    await this.focus.startSync.mutate({ mainRepoPath, worktreePath });
  }

  async stopSync(): Promise<void> {
    await this.focus.stopSync.mutate();
  }

  async startWatchingMainRepo(mainRepoPath: string): Promise<void> {
    await this.focus.startWatchingMainRepo.mutate({ mainRepoPath });
  }

  async stopWatchingMainRepo(): Promise<void> {
    await this.focus.stopWatchingMainRepo.mutate();
  }

  private async handleBranchRenamed(
    event: FocusBranchRenamedEvent,
  ): Promise<void> {
    const remoteSession = await this.focus.getSession
      .query({ mainRepoPath: event.mainRepoPath })
      .catch(() => null);
    const localSession = this.getSession(event.mainRepoPath);
    const sessionToPersist =
      remoteSession ??
      (localSession
        ? {
            ...localSession,
            branch: event.newBranch,
          }
        : null);

    if (sessionToPersist) {
      this.store.saveSession(sessionToPersist);
    }

    this.emit(FocusServiceEvent.BranchRenamed, event);
  }
}
