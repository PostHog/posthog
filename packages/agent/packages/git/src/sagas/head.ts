import { GitSaga, type GitSagaInput } from "../git-saga";

export interface DetachHeadInput extends GitSagaInput {}

export interface DetachHeadOutput {
  previousBranch: string | null;
  detachedAt: string;
}

export class DetachHeadSaga extends GitSaga<DetachHeadInput, DetachHeadOutput> {
  readonly sagaName = "DetachHeadSaga";

  protected async executeGitOperations(
    _input: DetachHeadInput,
  ): Promise<DetachHeadOutput> {
    const previousBranch = await this.readOnlyStep(
      "get-current-branch",
      async () => {
        const branch = await this.git.revparse(["--abbrev-ref", "HEAD"]);
        return branch === "HEAD" ? null : branch;
      },
    );

    const commitSha = await this.readOnlyStep("get-head-sha", () =>
      this.git.revparse(["HEAD"]),
    );

    await this.step({
      name: "detach-head",
      execute: () => this.git.checkout(["--detach"]),
      rollback: async () => {
        if (previousBranch) {
          await this.git.checkout(previousBranch);
        }
      },
    });

    return { previousBranch, detachedAt: commitSha };
  }
}

export interface ReattachBranchInput extends GitSagaInput {
  branchName: string;
}

export interface ReattachBranchOutput {
  branchName: string;
}

export class ReattachBranchSaga extends GitSaga<
  ReattachBranchInput,
  ReattachBranchOutput
> {
  readonly sagaName = "ReattachBranchSaga";
  private branchExistedBefore = false;
  private originalBranchSha: string | null = null;

  protected async executeGitOperations(
    input: ReattachBranchInput,
  ): Promise<ReattachBranchOutput> {
    const { branchName } = input;

    const originalHead = await this.readOnlyStep("get-head-sha", () =>
      this.git.revparse(["HEAD"]),
    );

    const branchInfo = await this.readOnlyStep(
      "check-branch-exists",
      async () => {
        try {
          const sha = await this.git.revparse([branchName]);
          return { exists: true, sha };
        } catch {
          return { exists: false, sha: null };
        }
      },
    );
    this.branchExistedBefore = branchInfo.exists;
    this.originalBranchSha = branchInfo.sha;

    await this.step({
      name: "reattach-branch",
      execute: () => this.git.checkout(["-B", branchName]),
      rollback: async () => {
        await this.git.checkout(["--detach", originalHead]);
        if (this.branchExistedBefore && this.originalBranchSha) {
          await this.git.raw([
            "branch",
            "-f",
            branchName,
            this.originalBranchSha,
          ]);
        } else if (!this.branchExistedBefore) {
          await this.git.deleteLocalBranch(branchName, true).catch(() => {});
        }
      },
    });

    return { branchName };
  }
}
