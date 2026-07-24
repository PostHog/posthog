import type { Task } from "@posthog/shared/domain-types";
import { inject, injectable } from "inversify";
import { SESSION_SERVICE, type SessionService } from "./sessionService";

export const LOCAL_HANDOFF_SERVICE = Symbol.for(
  "posthog.core.sessions.localHandoffService",
);

export const LOCAL_HANDOFF_HOST = Symbol.for(
  "posthog.core.sessions.localHandoffHost",
);

export const LOCAL_HANDOFF_DIALOG = Symbol.for(
  "posthog.core.sessions.localHandoffDialog",
);

export const LOCAL_HANDOFF_NOTIFIER = Symbol.for(
  "posthog.core.sessions.localHandoffNotifier",
);

export interface LocalHandoffHost {
  getRepositoryByRemoteUrl(input: {
    remoteUrl: string;
  }): Promise<{ path: string } | null>;
  selectDirectory(): Promise<string | null>;
  addFolder(input: {
    folderPath: string;
    remoteUrl?: string;
  }): Promise<unknown>;
}

export interface LocalHandoffPending {
  taskId: string;
  repoPath: string;
  branchName: string | null;
}

export interface ContinueAfterDirtyTreeContext {
  isFeatureBranch: boolean;
  suggestedBranchName: string;
}

export type ContinueAfterDirtyTreeStep =
  | { step: "open-commit" }
  | { step: "open-branch"; suggestedName: string };

export interface LocalHandoffDialog {
  openConfirm(taskId: string, branchName: string | null): void;
  closeConfirm(): void;
  cancelPendingFlow(): void;
  hideDirtyTree(): void;
  getPendingAfterCommit(): LocalHandoffPending | null;
  clearPendingAfterCommit(): void;
  openDirtyTreeForPendingHandoff(
    changedFiles: unknown[],
    pending: LocalHandoffPending,
  ): void;
}

export interface LocalHandoffNotifier {
  error(message: string): void;
  warn(message: string, data?: unknown): void;
  logError(message: string, data?: unknown): void;
}

@injectable()
export class LocalHandoffService {
  constructor(
    @inject(SESSION_SERVICE)
    private readonly sessionService: SessionService,
    @inject(LOCAL_HANDOFF_HOST)
    private readonly host: LocalHandoffHost,
    @inject(LOCAL_HANDOFF_DIALOG)
    private readonly dialog: LocalHandoffDialog,
    @inject(LOCAL_HANDOFF_NOTIFIER)
    private readonly notifier: LocalHandoffNotifier,
  ) {}

  public openConfirm(taskId: string, branchName: string | null): void {
    this.dialog.openConfirm(taskId, branchName);
  }

  public closeConfirm(): void {
    this.dialog.closeConfirm();
  }

  public cancelPendingFlow(): void {
    this.dialog.cancelPendingFlow();
  }

  public hideDirtyTree(): void {
    this.dialog.hideDirtyTree();
  }

  public getPendingAfterCommit(): LocalHandoffPending | null {
    return this.dialog.getPendingAfterCommit();
  }

  public async start(taskId: string, task: Task): Promise<void> {
    try {
      const targetPath =
        (await this.resolveRepoPathFromRemote(task.repository)) ??
        (await this.resolveRepoPathFromPicker(task.repository));

      if (!targetPath) return;

      const preflight = await this.sessionService.preflightToLocal(
        taskId,
        targetPath,
      );

      if (preflight.canHandoff) {
        this.closeConfirm();
        await this.sessionService.handoffToLocal(taskId, targetPath);
        return;
      }

      if (preflight.localTreeDirty && preflight.changedFiles) {
        this.dialog.openDirtyTreeForPendingHandoff(preflight.changedFiles, {
          taskId,
          repoPath: targetPath,
          branchName: preflight.localGitState?.branch ?? null,
        });
        return;
      }

      this.notifier.error(preflight.reason ?? "Cannot continue locally");
      this.closeConfirm();
    } catch (error) {
      this.notifier.logError("Failed to hand off to local", error);
      const message = error instanceof Error ? error.message : "Unknown error";
      this.notifier.error(`Failed to continue locally: ${message}`);
      this.closeConfirm();
    }
  }

  public continueAfterDirtyTree(
    ctx: ContinueAfterDirtyTreeContext,
  ): ContinueAfterDirtyTreeStep {
    this.dialog.hideDirtyTree();
    if (ctx.isFeatureBranch) {
      return { step: "open-commit" };
    }
    return { step: "open-branch", suggestedName: ctx.suggestedBranchName };
  }

  public afterBranchCreated(): ContinueAfterDirtyTreeStep {
    return { step: "open-commit" };
  }

  public async afterCommit(): Promise<void> {
    await this.resumePending();
  }

  public async resumePending(): Promise<void> {
    const pending = this.getPendingAfterCommit();
    if (!pending) return;

    this.dialog.clearPendingAfterCommit();

    try {
      await this.sessionService.handoffToLocal(
        pending.taskId,
        pending.repoPath,
      );
    } catch (error) {
      this.notifier.logError("Failed to resume handoff to local", error);
      const message = error instanceof Error ? error.message : "Unknown error";
      this.notifier.error(`Failed to continue locally: ${message}`);
    }
  }

  private async resolveRepoPathFromRemote(
    remoteUrl: string | undefined | null,
  ): Promise<string | null> {
    if (!remoteUrl) return null;
    const repo = await this.host.getRepositoryByRemoteUrl({
      remoteUrl,
    });
    return repo?.path ?? null;
  }

  private async resolveRepoPathFromPicker(
    remoteUrl: string | null | undefined,
  ): Promise<string | null> {
    const selectedPath = await this.host.selectDirectory();
    if (!selectedPath) return null;

    await this.host.addFolder({
      folderPath: selectedPath,
      remoteUrl: remoteUrl ?? undefined,
    });

    return selectedPath;
  }
}
