import { GitSaga, type GitSagaInput } from "../git-saga";

export interface SyncInput extends GitSagaInput {
  remote?: string;
  branch?: string;
}

export interface SyncOutput {
  pullSummary: {
    changes: number;
    insertions: number;
    deletions: number;
  };
  pushBranch: string;
}

export class SyncSaga extends GitSaga<SyncInput, SyncOutput> {
  readonly sagaName = "SyncSaga";
  private stashCreated = false;

  protected async executeGitOperations(input: SyncInput): Promise<SyncOutput> {
    const { remote = "origin", branch } = input;

    const originalHead = await this.readOnlyStep("get-original-head", () =>
      this.git.revparse(["HEAD"]),
    );

    const hasChanges = await this.readOnlyStep("check-changes", async () => {
      const status = await this.git.status();
      return !status.isClean();
    });

    if (hasChanges) {
      const stashCountBefore = await this.readOnlyStep(
        "get-stash-count",
        async () => {
          const result = await this.git.stashList();
          return result.all.length;
        },
      );

      await this.step({
        name: "stash-changes",
        execute: async () => {
          await this.git.stash([
            "push",
            "--include-untracked",
            "-m",
            "posthog-code-sync-backup",
          ]);
          const afterResult = await this.git.stashList();
          this.stashCreated = afterResult.all.length > stashCountBefore;
        },
        rollback: async () => {
          if (this.stashCreated) {
            await this.git.stash(["pop"]).catch(() => {});
          }
        },
      });
    }

    const currentBranch =
      branch ?? (await this.git.revparse(["--abbrev-ref", "HEAD"]));

    const pullResult = await this.step({
      name: "pull",
      execute: () => this.git.pull(remote, currentBranch),
      rollback: async () => {
        await this.git.reset(["--hard", originalHead]);
        if (this.stashCreated) {
          await this.git.stash(["pop"]).catch(() => {});
          this.stashCreated = false;
        }
      },
    });

    await this.step({
      name: "push",
      execute: () => this.git.push(remote, currentBranch),
      rollback: async () => {},
    });

    if (this.stashCreated) {
      await this.step({
        name: "restore-stash",
        execute: async () => {
          await this.git.stash(["pop"]);
          this.stashCreated = false;
        },
        rollback: async () => {},
      });
    }

    return {
      pullSummary: {
        changes: pullResult.summary.changes,
        insertions: pullResult.summary.insertions,
        deletions: pullResult.summary.deletions,
      },
      pushBranch: currentBranch,
    };
  }
}
