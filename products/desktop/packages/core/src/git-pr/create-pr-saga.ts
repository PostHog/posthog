import { Saga, type SagaLogger } from "@posthog/shared";

export type CreatePrStep =
  | "creating-branch"
  | "committing"
  | "pushing"
  | "creating-pr"
  | "complete"
  | "error";

/** Minimal shape the saga reads from a git write result (commit/push/publish). */
interface GitOpResult {
  success: boolean;
  message: string;
}

export interface CreatePrSagaInput {
  directoryPath: string;
  branchName?: string;
  commitMessage?: string;
  prTitle?: string;
  prBody?: string;
  draft?: boolean;
  stagedOnly?: boolean;
  taskId?: string;
}

export interface CreatePrSagaOutput {
  prUrl: string | null;
}

// Host git operations the saga orchestrates. The host (apps/code GitService)
// binds these to @posthog/git CLI calls; the saga itself stays host-agnostic.
export interface CreatePrDeps {
  getCurrentBranch(dir: string): Promise<string | null>;
  createBranch(dir: string, name: string): Promise<void>;
  getChangedFilesHead(dir: string): Promise<readonly unknown[]>;
  generateCommitMessage(dir: string): Promise<{ message: string }>;
  getHeadSha(dir: string): Promise<string>;
  commit(
    dir: string,
    message: string,
    options?: { stagedOnly?: boolean; taskId?: string },
  ): Promise<GitOpResult>;
  /** Soft-reset to `sha` (commit rollback). */
  resetSoft(dir: string, sha: string): Promise<void>;
  getSyncStatus(dir: string): Promise<{ hasRemote: boolean }>;
  push(dir: string): Promise<GitOpResult>;
  publish(dir: string): Promise<GitOpResult>;
  generatePrTitleAndBody(dir: string): Promise<{ title: string; body: string }>;
  createPr(
    dir: string,
    title?: string,
    body?: string,
    draft?: boolean,
  ): Promise<{ success: boolean; message: string; prUrl: string | null }>;
  onProgress(step: CreatePrStep, message: string, prUrl?: string): void;
}

export class CreatePrSaga extends Saga<CreatePrSagaInput, CreatePrSagaOutput> {
  readonly sagaName = "CreatePrSaga";
  private deps: CreatePrDeps;

  constructor(deps: CreatePrDeps, logger?: SagaLogger) {
    super(logger);
    this.deps = deps;
  }

  protected async execute(
    input: CreatePrSagaInput,
  ): Promise<CreatePrSagaOutput> {
    const { directoryPath, draft } = input;
    let { commitMessage, prTitle, prBody } = input;

    if (input.branchName) {
      const branchName = input.branchName;
      const currentBranch = await this.readOnlyStep("get-original-branch", () =>
        this.deps.getCurrentBranch(directoryPath),
      );

      // on retry, do not attempt to re-create the branch
      if (currentBranch !== branchName) {
        this.deps.onProgress(
          "creating-branch",
          `Creating branch ${branchName}...`,
        );

        await this.step({
          name: "creating-branch",
          execute: () => this.deps.createBranch(directoryPath, branchName),
          rollback: async () => {},
        });
      }
    }

    const changedFiles = await this.readOnlyStep("check-changes", () =>
      this.deps.getChangedFilesHead(directoryPath),
    );

    if (changedFiles.length > 0) {
      if (!commitMessage) {
        this.deps.onProgress("committing", "Generating commit message...");
        const generated = await this.readOnlyStep(
          "generate-commit-message",
          async () => {
            try {
              return await this.deps.generateCommitMessage(directoryPath);
            } catch {
              return null;
            }
          },
        );
        if (generated) commitMessage = generated.message;
      }

      if (!commitMessage) {
        throw new Error("Commit message is required.");
      }

      const finalCommitMessage = commitMessage;

      this.deps.onProgress("committing", "Committing changes...");

      const preCommitSha = await this.readOnlyStep("get-pre-commit-sha", () =>
        this.deps.getHeadSha(directoryPath),
      );

      await this.step({
        name: "committing",
        execute: async () => {
          const result = await this.deps.commit(
            directoryPath,
            finalCommitMessage,
            {
              stagedOnly: input.stagedOnly,
              taskId: input.taskId,
            },
          );
          if (!result.success) throw new Error(result.message);
          return result;
        },
        rollback: async () => {
          await this.deps.resetSoft(directoryPath, preCommitSha);
        },
      });
    }

    this.deps.onProgress("pushing", "Pushing to remote...");

    const syncStatus = await this.readOnlyStep("check-sync-status", () =>
      this.deps.getSyncStatus(directoryPath),
    );

    await this.step({
      name: "pushing",
      execute: async () => {
        const result = syncStatus.hasRemote
          ? await this.deps.push(directoryPath)
          : await this.deps.publish(directoryPath);
        if (!result.success) throw new Error(result.message);
        return result;
      },
      rollback: async () => {}, // no meaningful rollback can happen here w/o force push
    });

    if (!prTitle || !prBody) {
      this.deps.onProgress("creating-pr", "Generating PR description...");
      const generated = await this.readOnlyStep(
        "generate-pr-description",
        async () => {
          try {
            return await this.deps.generatePrTitleAndBody(directoryPath);
          } catch {
            return null;
          }
        },
      );
      if (generated) {
        if (!prTitle) prTitle = generated.title;
        if (!prBody) prBody = generated.body;
      }
    }

    this.deps.onProgress("creating-pr", "Creating pull request...");

    const prResult = await this.step({
      name: "creating-pr",
      execute: async () => {
        const result = await this.deps.createPr(
          directoryPath,
          prTitle || undefined,
          prBody || undefined,
          draft,
        );
        if (!result.success) throw new Error(result.message);
        return result;
      },
      rollback: async () => {},
    });

    return { prUrl: prResult.prUrl };
  }
}
