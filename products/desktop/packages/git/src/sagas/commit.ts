import { GitSaga, type GitSagaInput } from "../git-saga";
import { buildPostHogTrailers } from "../trailers";

export interface CommitInput extends GitSagaInput {
  message: string;
  paths?: string[];
  allowEmpty?: boolean;
  stagedOnly?: boolean;
  taskId?: string;
}

export interface CommitOutput {
  commitSha: string;
  branch: string;
}

export class CommitSaga extends GitSaga<CommitInput, CommitOutput> {
  readonly sagaName = "CommitSaga";
  private previouslyStagedFiles: string[] = [];

  protected async executeGitOperations(
    input: CommitInput,
  ): Promise<CommitOutput> {
    const { message, paths, allowEmpty, stagedOnly, taskId } = input;

    const originalHead = await this.readOnlyStep("get-original-head", () =>
      this.git.revparse(["HEAD"]),
    );

    const branch = await this.readOnlyStep("get-current-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    if (stagedOnly) {
      const stagedCheck = await this.readOnlyStep(
        "verify-staged-files",
        async () => {
          const status = await this.git.status();
          return status.staged;
        },
      );
      if (stagedCheck.length === 0) {
        throw new Error("No staged changes to commit.");
      }
    } else {
      this.previouslyStagedFiles = await this.readOnlyStep(
        "get-staged-files",
        async () => {
          const status = await this.git.status();
          return status.staged;
        },
      );

      await this.step({
        name: "stage-files",
        execute: () =>
          paths && paths.length > 0 ? this.git.add(paths) : this.git.add("-A"),
        rollback: async () => {
          await this.git.reset();
          if (this.previouslyStagedFiles.length > 0) {
            await this.git.add(this.previouslyStagedFiles);
          }
        },
      });
    }

    const trailers = buildPostHogTrailers(taskId);

    const commitOptions: Record<string, null | string[]> = {};
    if (allowEmpty) commitOptions["--allow-empty"] = null;
    if (trailers.length > 0) commitOptions["--trailer"] = trailers;

    const hasOptions = Object.keys(commitOptions).length > 0;

    const commitResult = await this.step({
      name: "commit",
      execute: () =>
        hasOptions
          ? this.git.commit(message, undefined, commitOptions)
          : this.git.commit(message),
      rollback: async () => {
        await this.git.reset(["--soft", originalHead]);
      },
    });

    return { commitSha: commitResult.commit, branch };
  }
}

export interface StageAndCommitInput extends GitSagaInput {
  message: string;
  paths: string[];
}

export interface StageAndCommitOutput {
  commitSha: string;
  branch: string;
  filesStaged: number;
}

export class StageAndCommitSaga extends GitSaga<
  StageAndCommitInput,
  StageAndCommitOutput
> {
  readonly sagaName = "StageAndCommitSaga";

  protected async executeGitOperations(
    input: StageAndCommitInput,
  ): Promise<StageAndCommitOutput> {
    const { message, paths } = input;

    const originalHead = await this.readOnlyStep("get-original-head", () =>
      this.git.revparse(["HEAD"]),
    );

    const branch = await this.readOnlyStep("get-current-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    await this.step({
      name: "stage-files",
      execute: () => this.git.add(paths),
      rollback: async () => {
        await this.git.reset(paths);
      },
    });

    const commitResult = await this.step({
      name: "commit",
      execute: () => this.git.commit(message),
      rollback: async () => {
        await this.git.reset(["--soft", originalHead]);
      },
    });

    return {
      commitSha: commitResult.commit,
      branch,
      filesStaged: paths.length,
    };
  }
}
