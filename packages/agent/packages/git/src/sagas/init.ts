import * as fs from "node:fs/promises";
import * as path from "node:path";
import { GitSaga, type GitSagaInput } from "../git-saga";

export interface InitRepositoryInput extends GitSagaInput {
  initialCommit?: boolean;
  commitMessage?: string;
}

export interface InitRepositoryOutput {
  initialized: boolean;
  commitSha?: string;
}

export class InitRepositorySaga extends GitSaga<
  InitRepositoryInput,
  InitRepositoryOutput
> {
  readonly sagaName = "InitRepositorySaga";
  private wasAlreadyRepo = false;

  protected async executeGitOperations(
    input: InitRepositoryInput,
  ): Promise<InitRepositoryOutput> {
    const {
      baseDir,
      initialCommit = true,
      commitMessage = "Initial commit",
    } = input;
    const gitDir = path.join(baseDir, ".git");

    this.wasAlreadyRepo = await this.readOnlyStep(
      "check-existing-repo",
      async () => {
        try {
          const stat = await fs.stat(gitDir);
          return stat.isDirectory();
        } catch {
          return false;
        }
      },
    );

    await this.step({
      name: "init",
      execute: () => this.git.init(),
      rollback: async () => {
        if (!this.wasAlreadyRepo) {
          await fs.rm(gitDir, { recursive: true, force: true }).catch(() => {});
        }
      },
    });

    if (initialCommit) {
      const result = await this.step({
        name: "initial-commit",
        execute: () =>
          this.git.commit(commitMessage, undefined, { "--allow-empty": null }),
        rollback: async () => {
          if (!this.wasAlreadyRepo) {
            await fs
              .rm(gitDir, { recursive: true, force: true })
              .catch(() => {});
          }
        },
      });
      return { initialized: true, commitSha: result.commit };
    }

    return { initialized: true };
  }
}
