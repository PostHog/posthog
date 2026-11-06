import { GitSaga, type GitSagaInput } from "../git-saga";

export interface PullInput extends GitSagaInput {
  remote?: string;
  branch?: string;
}

export interface PullOutput {
  changes: number;
  insertions: number;
  deletions: number;
}

export class PullSaga extends GitSaga<PullInput, PullOutput> {
  readonly sagaName = "PullSaga";
  private stashCreated = false;

  protected async executeGitOperations(input: PullInput): Promise<PullOutput> {
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
            "posthog-code-pull-backup",
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

    const targetBranch =
      branch ?? (await this.git.revparse(["--abbrev-ref", "HEAD"]));

    const result = await this.step({
      name: "pull",
      execute: () =>
        this.git.pull(
          remote,
          targetBranch === "HEAD" ? undefined : targetBranch,
        ),
      rollback: async () => {
        await this.git.reset(["--hard", originalHead]);
        if (this.stashCreated) {
          await this.git.stash(["pop"]).catch(() => {});
          this.stashCreated = false;
        }
      },
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
      changes: result.summary.changes,
      insertions: result.summary.insertions,
      deletions: result.summary.deletions,
    };
  }
}
