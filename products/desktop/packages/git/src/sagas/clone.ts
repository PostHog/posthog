import * as fs from "node:fs/promises";
import path from "node:path";
import { Saga } from "@posthog/shared";
import { createGitClient } from "../client";
import { getCleanEnv, getGitOperationManager } from "../operation-manager";

export interface CloneInput {
  repoUrl: string;
  targetPath: string;
  branch?: string;
  shallow?: boolean;
  env?: Record<string, string>;
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
    const { repoUrl, targetPath, branch, shallow, env, signal, onProgress } =
      input;
    const manager = getGitOperationManager();
    const targetParent = path.dirname(targetPath);
    await fs.mkdir(targetParent, { recursive: true });

    await manager.executeWrite(
      targetParent,
      async () => {
        await this.step({
          name: "clone",
          execute: async () => {
            const git = createGitClient(undefined, {
              abortSignal: signal,
              allowConfigEnv: env !== undefined,
              progress: onProgress
                ? ({ stage, progress, processed, total }) =>
                    onProgress(stage, progress, processed, total)
                : undefined,
            });
            const cloneArgs = ["--progress"];
            if (shallow) {
              cloneArgs.push("--depth", "1", "--single-branch", "--no-tags");
            }
            if (branch) {
              cloneArgs.push("--branch", branch);
            }
            await git
              .env({ ...getCleanEnv(), ...env })
              .clone(repoUrl, targetPath, cloneArgs);
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
