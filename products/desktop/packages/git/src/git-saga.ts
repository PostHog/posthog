import { Saga } from "@posthog/shared";
import type { GitClient } from "./client";
import { getGitOperationManager } from "./operation-manager";

export interface GitSagaInput {
  baseDir: string;
  signal?: AbortSignal;
  /**
   * Extra env vars merged on top of the clean env when spawning the git
   * subprocess. Used to pass through SessionStart-hook env so UI-triggered
   * commits see the same `SSH_AUTH_SOCK` (etc.) the agent does.
   */
  env?: Record<string, string>;
}

export abstract class GitSaga<
  TInput extends GitSagaInput,
  TOutput,
> extends Saga<TInput, TOutput> {
  private _git: GitClient | null = null;

  protected get git(): GitClient {
    if (!this._git) {
      throw new Error("git client accessed before execute() was called");
    }
    return this._git;
  }

  protected async execute(input: TInput): Promise<TOutput> {
    const manager = getGitOperationManager();

    return manager.executeWrite(
      input.baseDir,
      async (git) => {
        this._git = git;
        return this.executeGitOperations(input);
      },
      { signal: input.signal, env: input.env },
    );
  }

  protected abstract executeGitOperations(input: TInput): Promise<TOutput>;
}
