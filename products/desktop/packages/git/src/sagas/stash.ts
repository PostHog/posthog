import { GitSaga, type GitSagaInput } from "../git-saga";

export interface StashPushInput extends GitSagaInput {
  message: string;
}

export interface StashPushOutput {
  stashSha: string | null;
}

export class StashPushSaga extends GitSaga<StashPushInput, StashPushOutput> {
  readonly sagaName = "StashPushSaga";
  private previouslyStagedFiles: string[] = [];

  protected async executeGitOperations(
    input: StashPushInput,
  ): Promise<StashPushOutput> {
    const { message } = input;

    const beforeCount = await this.readOnlyStep(
      "get-before-count",
      async () => {
        const result = await this.git.stashList();
        return result.all.length;
      },
    );

    this.previouslyStagedFiles = await this.readOnlyStep(
      "get-staged-files",
      async () => {
        const status = await this.git.status();
        return status.staged;
      },
    );

    await this.step({
      name: "stage-all",
      execute: () => this.git.add("-A"),
      rollback: async () => {
        await this.git.reset();
        if (this.previouslyStagedFiles.length > 0) {
          await this.git.add(this.previouslyStagedFiles);
        }
      },
    });

    await this.step({
      name: "stash-push",
      execute: () =>
        this.git.stash(["push", "--include-untracked", "-m", message]),
      rollback: async () => {
        const afterResult = await this.git.stashList();
        if (afterResult.all.length > beforeCount) {
          await this.git.stash(["pop"]);
        }
      },
    });

    const stashSha = await this.readOnlyStep("get-stash-sha", async () => {
      const afterResult = await this.git.stashList();
      if (afterResult.all.length > beforeCount) {
        return this.git.revparse(["stash@{0}"]);
      }
      return null;
    });

    return { stashSha };
  }
}

export interface StashApplyInput extends GitSagaInput {
  stashSha: string;
}

export interface StashApplyOutput {
  dropped: boolean;
}

export class StashApplySaga extends GitSaga<StashApplyInput, StashApplyOutput> {
  readonly sagaName = "StashApplySaga";
  private backupStashCreated = false;
  private stashCountBeforeBackup = 0;

  protected async executeGitOperations(
    input: StashApplyInput,
  ): Promise<StashApplyOutput> {
    const { stashSha } = input;

    const hasExistingChanges = await this.readOnlyStep(
      "check-existing-changes",
      async () => {
        const status = await this.git.status();
        return !status.isClean();
      },
    );

    if (hasExistingChanges) {
      this.stashCountBeforeBackup = await this.readOnlyStep(
        "get-stash-count-before-backup",
        async () => {
          const result = await this.git.stashList();
          return result.all.length;
        },
      );

      await this.step({
        name: "backup-existing-changes",
        execute: async () => {
          await this.git.stash([
            "push",
            "--include-untracked",
            "-m",
            "posthog-code-stash-apply-backup",
          ]);
          const afterResult = await this.git.stashList();
          this.backupStashCreated =
            afterResult.all.length > this.stashCountBeforeBackup;
        },
        rollback: async () => {
          if (this.backupStashCreated) {
            await this.git.stash(["pop"]).catch(() => {});
          }
        },
      });
    }

    await this.step({
      name: "apply-stash",
      execute: () => this.git.stash(["apply", stashSha]),
      rollback: async () => {
        await this.git.reset(["--hard"]);
        await this.git.clean(["f", "d"]);
        if (this.backupStashCreated) {
          await this.git.stash(["pop"]).catch(() => {});
          this.backupStashCreated = false;
        }
      },
    });

    if (this.backupStashCreated) {
      await this.step({
        name: "restore-backup",
        execute: async () => {
          await this.git.stash(["pop"]);
          this.backupStashCreated = false;
        },
        rollback: async () => {},
      });
    }

    const stashIndex = await this.readOnlyStep("find-stash-index", async () => {
      const result = await this.git.raw([
        "reflog",
        "show",
        "--format=%H %gd",
        "refs/stash",
      ]);
      const match = result
        .split("\n")
        .find((line) => line.startsWith(stashSha));
      return match ? match.split(" ")[1] : null;
    });

    let dropped = false;
    if (stashIndex) {
      await this.step({
        name: "drop-stash",
        execute: async () => {
          await this.git.stash(["drop", stashIndex]);
          dropped = true;
        },
        rollback: async () => {},
      });
    }

    return { dropped };
  }
}

export interface StashPopInput extends GitSagaInput {}

export interface StashPopOutput {
  popped: boolean;
}

export class StashPopSaga extends GitSaga<StashPopInput, StashPopOutput> {
  readonly sagaName = "StashPopSaga";
  private stashSha: string | null = null;
  private stashMessage: string | null = null;

  protected async executeGitOperations(
    _input: StashPopInput,
  ): Promise<StashPopOutput> {
    const stashInfo = await this.readOnlyStep("get-stash-info", async () => {
      try {
        const sha = await this.git.revparse(["stash@{0}"]);
        const result = await this.git.stashList();
        const message =
          result.all.length > 0
            ? result.all[0].message || "posthog-code-stash-pop-restore"
            : "posthog-code-stash-pop-restore";
        return { sha, message };
      } catch {
        return { sha: null, message: "posthog-code-stash-pop-restore" };
      }
    });
    this.stashSha = stashInfo.sha;
    this.stashMessage = stashInfo.message;

    await this.step({
      name: "stash-pop",
      execute: () => this.git.stash(["pop"]),
      rollback: async () => {
        if (!this.stashSha || !this.stashMessage) return;
        await this.git.reset(["--hard"]).catch(() => {});
        await this.git.clean(["f", "d"]).catch(() => {});
        await this.git
          .raw(["stash", "store", "-m", this.stashMessage, this.stashSha])
          .catch(() => {});
      },
    });

    return { popped: true };
  }
}
