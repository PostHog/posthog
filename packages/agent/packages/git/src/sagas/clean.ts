import type { GitClient } from "../client";
import { GitSaga, type GitSagaInput } from "../git-saga";

export interface CleanWorkingTreeInput extends GitSagaInput {}

export interface CleanWorkingTreeOutput {
  cleaned: boolean;
  backupStashSha: string | null;
}

export class CleanWorkingTreeSaga extends GitSaga<
  CleanWorkingTreeInput,
  CleanWorkingTreeOutput
> {
  readonly sagaName = "CleanWorkingTreeSaga";
  private backupStashCreated = false;
  private stashCountBefore = 0;

  private async restoreBackupStash(git: GitClient): Promise<void> {
    if (this.backupStashCreated) {
      await git.stash(["pop"]).catch(() => {});
      this.backupStashCreated = false;
    }
  }

  protected async executeGitOperations(
    _input: CleanWorkingTreeInput,
  ): Promise<CleanWorkingTreeOutput> {
    const hasChanges = await this.readOnlyStep("check-changes", async () => {
      const status = await this.git.status();
      return !status.isClean();
    });

    if (hasChanges) {
      this.stashCountBefore = await this.readOnlyStep(
        "get-stash-count",
        async () => {
          const result = await this.git.stashList();
          return result.all.length;
        },
      );

      await this.step({
        name: "backup-changes",
        execute: async () => {
          await this.git.add("-A");
          await this.git.stash([
            "push",
            "--include-untracked",
            "-m",
            "posthog-code-clean-backup",
          ]);
          const afterResult = await this.git.stashList();
          this.backupStashCreated =
            afterResult.all.length > this.stashCountBefore;
        },
        rollback: () => this.restoreBackupStash(this.git),
      });
    }

    await this.step({
      name: "reset-index",
      execute: () => this.git.reset(),
      rollback: () => this.restoreBackupStash(this.git),
    });

    await this.step({
      name: "restore-working-tree",
      execute: () => this.git.raw(["restore", "."]),
      rollback: () => this.restoreBackupStash(this.git),
    });

    await this.step({
      name: "clean-untracked",
      execute: () => this.git.clean(["f", "d"]),
      rollback: () => this.restoreBackupStash(this.git),
    });

    let backupStashSha: string | null = null;
    if (this.backupStashCreated) {
      backupStashSha = await this.readOnlyStep("get-backup-sha", async () => {
        try {
          return await this.git.revparse(["stash@{0}"]);
        } catch {
          return null;
        }
      });
    }

    return { cleaned: true, backupStashSha };
  }
}
