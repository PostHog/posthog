import { GitSaga, type GitSagaInput } from "../git-saga";
import { detectDefaultBranch } from "../queries";

export interface CreateBranchInput extends GitSagaInput {
  branchName: string;
  baseBranch?: string;
}

export interface CreateBranchOutput {
  branchName: string;
  baseBranch: string;
}

export class CreateBranchSaga extends GitSaga<
  CreateBranchInput,
  CreateBranchOutput
> {
  readonly sagaName = "CreateBranchSaga";

  protected async executeGitOperations(
    input: CreateBranchInput,
  ): Promise<CreateBranchOutput> {
    const { branchName, baseBranch } = input;

    const originalBranch = await this.readOnlyStep("get-original-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    const base = baseBranch ?? originalBranch;

    await this.step({
      name: "create-branch",
      execute: () => this.git.checkoutBranch(branchName, base),
      rollback: async () => {
        await this.git.checkout(originalBranch);
        try {
          await this.git.deleteLocalBranch(branchName, true);
        } catch {}
      },
    });

    return { branchName, baseBranch: base };
  }
}

export interface SwitchBranchInput extends GitSagaInput {
  branchName: string;
}

export interface SwitchBranchOutput {
  previousBranch: string;
  currentBranch: string;
}

export class SwitchBranchSaga extends GitSaga<
  SwitchBranchInput,
  SwitchBranchOutput
> {
  readonly sagaName = "SwitchBranchSaga";

  protected async executeGitOperations(
    input: SwitchBranchInput,
  ): Promise<SwitchBranchOutput> {
    const { branchName } = input;

    const originalBranch = await this.readOnlyStep("get-original-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    await this.step({
      name: "switch-branch",
      execute: () => this.git.checkout(branchName),
      rollback: async () => {
        await this.git.checkout(originalBranch);
      },
    });

    return { previousBranch: originalBranch, currentBranch: branchName };
  }
}

export interface CreateOrSwitchBranchInput extends GitSagaInput {
  branchName: string;
  baseBranch?: string;
}

export interface CreateOrSwitchBranchOutput {
  branchName: string;
  created: boolean;
}

export class CreateOrSwitchBranchSaga extends GitSaga<
  CreateOrSwitchBranchInput,
  CreateOrSwitchBranchOutput
> {
  readonly sagaName = "CreateOrSwitchBranchSaga";
  private branchCreated = false;

  protected async executeGitOperations(
    input: CreateOrSwitchBranchInput,
  ): Promise<CreateOrSwitchBranchOutput> {
    const { branchName, baseBranch } = input;

    const originalBranch = await this.readOnlyStep("get-original-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    const branchExists = await this.readOnlyStep(
      "check-branch-exists",
      async () => {
        try {
          await this.git.revparse(["--verify", branchName]);
          return true;
        } catch {
          return false;
        }
      },
    );

    if (branchExists) {
      await this.step({
        name: "switch-to-existing",
        execute: () => this.git.checkout(branchName),
        rollback: async () => {
          await this.git.checkout(originalBranch);
        },
      });
    } else {
      const base = baseBranch ?? originalBranch;

      await this.step({
        name: "create-new-branch",
        execute: async () => {
          await this.git.checkoutBranch(branchName, base);
          this.branchCreated = true;
        },
        rollback: async () => {
          await this.git.checkout(originalBranch);
          if (this.branchCreated) {
            try {
              await this.git.deleteLocalBranch(branchName, true);
            } catch {}
          }
        },
      });
    }

    return { branchName, created: !branchExists };
  }
}

export interface ResetToDefaultBranchInput extends GitSagaInput {}

export interface ResetToDefaultBranchOutput {
  previousBranch: string;
  defaultBranch: string;
  switched: boolean;
}

export class ResetToDefaultBranchSaga extends GitSaga<
  ResetToDefaultBranchInput,
  ResetToDefaultBranchOutput
> {
  readonly sagaName = "ResetToDefaultBranchSaga";

  protected async executeGitOperations(
    _input: ResetToDefaultBranchInput,
  ): Promise<ResetToDefaultBranchOutput> {
    const originalBranch = await this.readOnlyStep("get-current-branch", () =>
      this.git.revparse(["--abbrev-ref", "HEAD"]),
    );

    const defaultBranch = await this.readOnlyStep("get-default-branch", () =>
      detectDefaultBranch(this.git),
    );

    if (originalBranch === defaultBranch) {
      return { previousBranch: originalBranch, defaultBranch, switched: false };
    }

    const hasChanges = await this.readOnlyStep("check-changes", async () => {
      const status = await this.git.status();
      return !status.isClean();
    });

    if (hasChanges) {
      throw new Error(
        "Uncommitted changes detected. Please commit or stash before switching branches.",
      );
    }

    await this.step({
      name: "switch-to-default",
      execute: () => this.git.checkout(defaultBranch),
      rollback: async () => {
        await this.git.checkout(originalBranch);
      },
    });

    return { previousBranch: originalBranch, defaultBranch, switched: true };
  }
}
