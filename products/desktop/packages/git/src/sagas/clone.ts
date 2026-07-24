import * as fs from "node:fs/promises";
import { Saga } from "@posthog/shared";
import { createGitClient } from "../client";
import { getCleanEnv, getGitOperationManager } from "../operation-manager";

export interface CloneInput {
  repoUrl: string;
  targetPath: string;
  signal?: AbortSignal;
  onProgress?: (
    stage: string,
    progress: number,
    processed: number,
    total: number,
  ) => void;
}

export interface CloneOutput {
  targetPath: string;
}

export class CloneSaga extends Saga<CloneInput, CloneOutput> {
  readonly sagaName = "CloneSaga";

  protected async execute(input: CloneInput): Promise<CloneOutput> {
    const { repoUrl, targetPath, signal, onProgress } = input;
    const manager = getGitOperationManager();

    await manager.executeWrite(
      targetPath,
      async () => {
        await this.step({
          name: "clone",
          execute: async () => {
            const git = createGitClient(undefined, {
              abortSignal: signal,
              progress: onProgress
                ? ({ stage, progress, processed, total }) =>
                    onProgress(stage, progress, processed, total)
                : undefined,
            });
            await git
              .env(getCleanEnv())
              .clone(repoUrl, targetPath, ["--progress"]);
          },
          rollback: async () => {
            try {
              await fs.rm(targetPath, { recursive: true, force: true });
            } catch {}
          },
        });
      },
      { signal, waitForExternalLock: false },
    );

    return { targetPath };
  }
}
