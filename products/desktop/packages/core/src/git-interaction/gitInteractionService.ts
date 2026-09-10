import { inject, injectable } from "inversify";
import type {
  CommitOutput,
  CreatePrOutput,
  CreatePrStep,
  GitStateSnapshot,
  OpenPrOutput,
  PublishOutput,
  PushOutput,
  SyncOutput,
} from "../git/router-schemas";
import { createBranch } from "./branchCreation";
import { GIT_INTERACTION_EFFECTS, GIT_WRITE_CLIENT } from "./identifiers";

export type GitPushMode = "push" | "sync" | "publish";

export type GitActionType =
  | "commit"
  | "push"
  | "sync"
  | "publish"
  | "create-pr"
  | "view-pr"
  | "update-pr"
  | "branch-here";

export interface GitStagingContext {
  staged_file_count: number;
  unstaged_file_count: number;
  commit_all: boolean;
  staged_only: boolean;
}

export interface IGitWriteClient {
  commit(input: {
    directoryPath: string;
    message: string;
    stagedOnly?: boolean;
    taskId: string;
  }): Promise<CommitOutput>;
  push(directoryPath: string, signal: AbortSignal): Promise<PushOutput>;
  sync(directoryPath: string, signal: AbortSignal): Promise<SyncOutput>;
  publish(directoryPath: string, signal: AbortSignal): Promise<PublishOutput>;
  createBranch(directoryPath: string, branchName: string): Promise<void>;
  createPr(input: {
    directoryPath: string;
    flowId: string;
    branchName?: string;
    commitMessage?: string;
    prTitle?: string;
    prBody?: string;
    draft?: boolean;
    stagedOnly?: boolean;
    taskId: string;
    conversationContext?: string;
  }): Promise<CreatePrOutput>;
  openPr(directoryPath: string): Promise<OpenPrOutput>;
  generateCommitMessage(input: {
    directoryPath: string;
    conversationContext?: string;
  }): Promise<{ message: string }>;
  generatePrTitleAndBody(input: {
    directoryPath: string;
    conversationContext?: string;
  }): Promise<{ title: string; body: string }>;
  linkBranch(taskId: string, branchName: string): Promise<void>;
  onCreatePrProgress(
    flowId: string,
    onStep: (step: CreatePrStep) => void,
  ): () => void;
}

export interface GitInteractionEffects {
  trackGitAction(
    taskId: string,
    actionType: GitActionType,
    success: boolean,
    stagingContext?: GitStagingContext,
  ): void;
  trackPrCreated(taskId: string, success: boolean): void;
  hasShippedFirstPr(): boolean;
  markFirstPrShipped(): void;
  celebrate(): void;
  openExternalUrl(url: string): void;
  attachPrUrlToTask(taskId: string, prUrl: string, prTitle?: string): void;
  getConversationContext(taskId: string): string | undefined;
  logError(message: string, error: unknown): void;
  logWarn(message: string, context: Record<string, unknown>): void;
}

export interface RunCommitInput {
  repoPath: string;
  taskId: string;
  message: string;
  stagedOnly: boolean;
  stagingContext: GitStagingContext;
  hasRemote: boolean;
  pushDisabledReason: string | null;
  commitPush: boolean;
}

export type RunCommitResult =
  | { outcome: "error"; message: string }
  | { outcome: "generate-failed"; message: string }
  | {
      outcome: "committed";
      snapshot?: GitStateSnapshot;
      generatedMessage?: string;
      next?: { mode: GitPushMode; result: RunPushResult };
    };

export interface RunPushInput {
  repoPath: string;
  taskId: string;
  mode: GitPushMode;
  signal: AbortSignal;
}

export type RunPushResult =
  | { outcome: "success"; snapshot?: GitStateSnapshot }
  | { outcome: "error"; message: string }
  | { outcome: "aborted" };

export interface RunBranchInput {
  repoPath: string;
  taskId: string;
  rawBranchName: string;
}

export type RunBranchResult =
  | { outcome: "success"; branchName: string }
  | { outcome: "error"; message: string };

export interface RunCreatePrInput {
  repoPath: string;
  taskId: string;
  flowId: string;
  needsBranch: boolean;
  branchName: string;
  currentBranch: string | null;
  commitMessage: string;
  prTitle: string;
  prBody: string;
  draft: boolean;
  stagedOnly: boolean;
  stagingContext: GitStagingContext;
  onStep: (step: CreatePrStep) => void;
}

export type RunCreatePrResult =
  | {
      outcome: "success";
      snapshot?: GitStateSnapshot;
      prUrl: string | null;
      linkedBranchName: string | null;
      branchInvalidated: boolean;
    }
  | { outcome: "error"; message: string; failedStep: CreatePrStep | null };

@injectable()
export class GitInteractionService {
  constructor(
    @inject(GIT_WRITE_CLIENT)
    private readonly git: IGitWriteClient,
    @inject(GIT_INTERACTION_EFFECTS)
    private readonly effects: GitInteractionEffects,
  ) {}

  async runCommit(input: RunCommitInput): Promise<RunCommitResult> {
    if (input.commitPush && input.pushDisabledReason) {
      return { outcome: "error", message: input.pushDisabledReason };
    }

    let message = input.message;
    let generatedMessage: string | undefined;

    if (!message) {
      const generated = await this.generateMessageForCommit(input);
      if (generated.outcome !== "ok") return generated.result;
      message = generated.message;
      generatedMessage = generated.message;
    }

    const result = await this.git.commit({
      directoryPath: input.repoPath,
      message,
      stagedOnly: input.stagedOnly || undefined,
      taskId: input.taskId,
    });

    if (!result.success) {
      this.effects.trackGitAction(
        input.taskId,
        "commit",
        false,
        input.stagingContext,
      );
      return { outcome: "error", message: result.message || "Commit failed." };
    }

    this.effects.trackGitAction(
      input.taskId,
      "commit",
      true,
      input.stagingContext,
    );

    let next: { mode: GitPushMode; result: RunPushResult } | undefined;
    if (input.commitPush) {
      const mode: GitPushMode = input.hasRemote ? "push" : "publish";
      const controller = new AbortController();
      const pushResult = await this.runPush({
        repoPath: input.repoPath,
        taskId: input.taskId,
        mode,
        signal: controller.signal,
      });
      next = { mode, result: pushResult };
    }

    return {
      outcome: "committed",
      snapshot: result.state,
      generatedMessage,
      next,
    };
  }

  private async generateMessageForCommit(
    input: RunCommitInput,
  ): Promise<
    | { outcome: "ok"; message: string }
    | { outcome: "failed"; result: RunCommitResult }
  > {
    try {
      const generated = await this.git.generateCommitMessage({
        directoryPath: input.repoPath,
        conversationContext: this.effects.getConversationContext(input.taskId),
      });
      if (!generated.message) {
        return {
          outcome: "failed",
          result: {
            outcome: "generate-failed",
            message: "No changes detected to generate a commit message.",
          },
        };
      }
      return { outcome: "ok", message: generated.message };
    } catch (error) {
      this.effects.logError("Failed to generate commit message", error);
      return {
        outcome: "failed",
        result: {
          outcome: "generate-failed",
          message:
            error instanceof Error
              ? error.message
              : "Failed to generate commit message.",
        },
      };
    }
  }

  async runPush(input: RunPushInput): Promise<RunPushResult> {
    try {
      const result = await this.dispatchPush(input);

      if (!result.success) {
        const message =
          "message" in result
            ? result.message
            : `Pull: ${result.pullMessage}, Push: ${result.pushMessage}`;
        this.effects.trackGitAction(input.taskId, input.mode, false);
        return { outcome: "error", message: message || "Push failed." };
      }

      this.effects.trackGitAction(input.taskId, input.mode, true);
      return { outcome: "success", snapshot: result.state };
    } catch (error) {
      this.effects.trackGitAction(input.taskId, input.mode, false);
      if (input.signal.aborted) {
        return { outcome: "aborted" };
      }
      this.effects.logError("Push failed", error);
      return {
        outcome: "error",
        message: error instanceof Error ? error.message : "Push failed.",
      };
    }
  }

  private dispatchPush(
    input: RunPushInput,
  ): Promise<PushOutput | SyncOutput | PublishOutput> {
    if (input.mode === "sync") {
      return this.git.sync(input.repoPath, input.signal);
    }
    if (input.mode === "publish") {
      return this.git.publish(input.repoPath, input.signal);
    }
    return this.git.push(input.repoPath, input.signal);
  }

  async runBranch(input: RunBranchInput): Promise<RunBranchResult> {
    const result = await createBranch({
      writeClient: {
        createBranch: (directoryPath: string, branchName: string) =>
          this.git.createBranch(directoryPath, branchName),
      },
      repoPath: input.repoPath,
      rawBranchName: input.rawBranchName,
    });

    if (!result.success) {
      if (result.reason === "request") {
        this.effects.logError(
          "Failed to create branch",
          result.rawError ?? result.error,
        );
        this.effects.trackGitAction(input.taskId, "branch-here", false);
      }
      return { outcome: "error", message: result.error };
    }

    this.effects.trackGitAction(input.taskId, "branch-here", true);

    this.git.linkBranch(input.taskId, result.branchName).catch((err) =>
      this.effects.logWarn("Failed to link branch to task", {
        taskId: input.taskId,
        err,
      }),
    );

    return { outcome: "success", branchName: result.branchName };
  }

  async runCreatePr(input: RunCreatePrInput): Promise<RunCreatePrResult> {
    const unsubscribe = this.git.onCreatePrProgress(input.flowId, input.onStep);

    try {
      const result = await this.git.createPr({
        directoryPath: input.repoPath,
        flowId: input.flowId,
        branchName: input.needsBranch ? input.branchName.trim() : undefined,
        commitMessage: input.commitMessage.trim() || undefined,
        prTitle: input.prTitle.trim() || undefined,
        prBody: input.prBody.trim() || undefined,
        draft: input.draft || undefined,
        stagedOnly: input.stagedOnly || undefined,
        taskId: input.taskId,
        conversationContext: this.effects.getConversationContext(input.taskId),
      });

      if (!result.success) {
        this.effects.trackGitAction(
          input.taskId,
          "create-pr",
          false,
          input.stagingContext,
        );
        return {
          outcome: "error",
          message: result.message,
          failedStep: result.failedStep ?? null,
        };
      }

      this.effects.trackGitAction(
        input.taskId,
        "create-pr",
        true,
        input.stagingContext,
      );
      this.effects.trackPrCreated(input.taskId, true);

      if (!this.effects.hasShippedFirstPr()) {
        this.effects.markFirstPrShipped();
        this.effects.celebrate();
      }

      const linkedBranchName = input.needsBranch
        ? input.branchName.trim()
        : input.currentBranch;

      if (result.prUrl) {
        this.effects.openExternalUrl(result.prUrl);
        this.effects.attachPrUrlToTask(
          input.taskId,
          result.prUrl,
          input.prTitle.trim() || undefined,
        );
      }

      return {
        outcome: "success",
        snapshot: result.state,
        prUrl: result.prUrl,
        linkedBranchName,
        branchInvalidated: input.needsBranch,
      };
    } catch (error) {
      this.effects.logError("Create PR flow failed", error);
      return {
        outcome: "error",
        message:
          error instanceof Error ? error.message : "Create PR flow failed.",
        failedStep: null,
      };
    } finally {
      unsubscribe();
    }
  }

  async viewPr(repoPath: string): Promise<string | null> {
    const result = await this.git.openPr(repoPath);
    if (result.success && result.prUrl) {
      return result.prUrl;
    }
    return null;
  }

  async generateCommitMessage(
    repoPath: string,
    taskId: string,
  ): Promise<{ message: string } | { error: string }> {
    try {
      const result = await this.git.generateCommitMessage({
        directoryPath: repoPath,
        conversationContext: this.effects.getConversationContext(taskId),
      });
      if (result.message) return { message: result.message };
      return { error: "No changes detected to generate a commit message." };
    } catch (error) {
      this.effects.logError("Failed to generate commit message", error);
      return {
        error:
          error instanceof Error
            ? error.message
            : "Failed to generate commit message.",
      };
    }
  }

  async generatePrTitleAndBody(
    repoPath: string,
    taskId: string,
  ): Promise<{ title: string; body: string } | { error: string }> {
    try {
      const result = await this.git.generatePrTitleAndBody({
        directoryPath: repoPath,
        conversationContext: this.effects.getConversationContext(taskId),
      });
      if (result.title || result.body) {
        return { title: result.title, body: result.body };
      }
      return { error: "No changes detected to generate PR description." };
    } catch (error) {
      this.effects.logError("Failed to generate PR title and body", error);
      return {
        error:
          error instanceof Error
            ? error.message
            : "Failed to generate PR description.",
      };
    }
  }
}
