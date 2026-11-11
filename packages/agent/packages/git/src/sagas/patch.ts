import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { GitSaga, type GitSagaInput } from "../git-saga";

export interface ApplyPatchInput extends GitSagaInput {
  patch: string;
  cached?: boolean;
}

export interface ApplyPatchOutput {
  applied: boolean;
}

export class ApplyPatchSaga extends GitSaga<ApplyPatchInput, ApplyPatchOutput> {
  readonly sagaName = "ApplyPatchSaga";
  private tempFile: string | null = null;
  private cached = false;

  protected async executeGitOperations(
    input: ApplyPatchInput,
  ): Promise<ApplyPatchOutput> {
    const { patch, cached = false } = input;
    this.cached = cached;

    this.tempFile = path.join(
      os.tmpdir(),
      `posthog-code-patch-${Date.now()}-${Math.random().toString(36).slice(2)}.patch`,
    );

    const tempFile = this.tempFile;

    await this.step({
      name: "write-patch-file",
      execute: () => fs.writeFile(tempFile, patch, "utf-8"),
      rollback: () => fs.rm(tempFile, { force: true }),
    });

    const options = cached ? ["--cached"] : [];

    await this.step({
      name: "apply-patch",
      execute: () => this.git.applyPatch([tempFile], options),
      rollback: async () => {
        const reverseOptions = this.cached
          ? ["--reverse", "--cached"]
          : ["--reverse"];
        await this.git.applyPatch([tempFile], reverseOptions).catch(() => {});
      },
    });

    await fs.rm(tempFile, { force: true });

    return { applied: true };
  }
}
