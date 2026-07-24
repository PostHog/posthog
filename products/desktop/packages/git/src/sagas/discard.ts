import * as fs from "node:fs/promises";
import * as path from "node:path";
import { GitSaga, type GitSagaInput } from "../git-saga";

export type GitFileStatus =
  | "modified"
  | "added"
  | "deleted"
  | "renamed"
  | "untracked";

export interface DiscardFileChangesInput extends GitSagaInput {
  filePath: string;
  fileStatus: GitFileStatus;
}

export interface DiscardFileChangesOutput {
  discarded: boolean;
  backupStashSha: string | null;
}

export class DiscardFileChangesSaga extends GitSaga<
  DiscardFileChangesInput,
  DiscardFileChangesOutput
> {
  readonly sagaName = "DiscardFileChangesSaga";
  private backupContent: Buffer | null = null;
  private backupStashSha: string | null = null;
  private stashCountBefore = 0;
  private backupStashCreated = false;

  protected async executeGitOperations(
    input: DiscardFileChangesInput,
  ): Promise<DiscardFileChangesOutput> {
    const { baseDir, filePath, fileStatus } = input;
    const fullPath = path.join(baseDir, filePath);

    if (
      fileStatus === "modified" ||
      fileStatus === "added" ||
      fileStatus === "untracked"
    ) {
      this.backupContent = await this.readOnlyStep(
        "backup-file-content",
        async () => {
          try {
            return await fs.readFile(fullPath);
          } catch {
            return null;
          }
        },
      );
    }

    if (fileStatus === "modified" || fileStatus === "renamed") {
      this.stashCountBefore = await this.readOnlyStep(
        "get-stash-count",
        async () => {
          const result = await this.git.stashList();
          return result.all.length;
        },
      );

      await this.step({
        name: "stash-file-changes",
        execute: async () => {
          await this.git.stash([
            "push",
            "--include-untracked",
            "-m",
            `posthog-code-discard-backup: ${filePath}`,
            "--",
            filePath,
          ]);
          const afterResult = await this.git.stashList();
          this.backupStashCreated =
            afterResult.all.length > this.stashCountBefore;
          if (this.backupStashCreated) {
            this.backupStashSha = await this.git.revparse(["stash@{0}"]);
          }
        },
        rollback: async () => {
          if (this.backupStashCreated) {
            await this.git.stash(["pop"]).catch(() => {});
          }
        },
      });

      return { discarded: true, backupStashSha: this.backupStashSha };
    }

    switch (fileStatus) {
      case "deleted":
        await this.step({
          name: "checkout-file",
          execute: () => this.git.checkout(["HEAD", "--", filePath]),
          rollback: async () => {
            await fs.rm(fullPath, { force: true }).catch(() => {});
          },
        });
        break;

      case "added":
        await this.step({
          name: "remove-staged-file",
          execute: () => this.git.rm(["-f", filePath]),
          rollback: async () => {
            if (this.backupContent) {
              const dir = path.dirname(fullPath);
              await fs.mkdir(dir, { recursive: true }).catch(() => {});
              await fs.writeFile(fullPath, this.backupContent);
              await this.git.add(filePath).catch(() => {});
            }
          },
        });
        break;

      case "untracked":
        await this.step({
          name: "clean-untracked-file",
          execute: () => this.git.clean("f", ["--", filePath]),
          rollback: async () => {
            if (this.backupContent) {
              const dir = path.dirname(fullPath);
              await fs.mkdir(dir, { recursive: true }).catch(() => {});
              await fs.writeFile(fullPath, this.backupContent);
            }
          },
        });
        break;

      default:
        throw new Error(`Unknown file status: ${fileStatus}`);
    }

    return { discarded: true, backupStashSha: null };
  }
}
