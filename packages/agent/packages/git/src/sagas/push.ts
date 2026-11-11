import { GitSaga, type GitSagaInput } from "../git-saga";

export interface PushInput extends GitSagaInput {
  remote?: string;
  branch?: string;
  setUpstream?: boolean;
}

export interface PushOutput {
  branch: string;
  remote: string;
}

export class PushSaga extends GitSaga<PushInput, PushOutput> {
  readonly sagaName = "PushSaga";

  protected async executeGitOperations(input: PushInput): Promise<PushOutput> {
    const { remote = "origin", branch, setUpstream = false } = input;

    const targetBranch =
      branch ?? (await this.git.revparse(["--abbrev-ref", "HEAD"]));
    if (targetBranch === "HEAD") {
      throw new Error("Cannot push: HEAD is detached");
    }

    const args = setUpstream
      ? ["-u", remote, targetBranch]
      : [remote, targetBranch];

    await this.step({
      name: "push",
      execute: () => this.git.push(args),
      rollback: async () => {},
    });

    return { branch: targetBranch, remote };
  }
}
