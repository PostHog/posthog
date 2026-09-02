import type { FileDiffMetadata } from "@pierre/diffs";
import { diffAcceptRejectHunk } from "@pierre/diffs";
import { inject, injectable } from "inversify";
import {
  CODE_REVIEW_WORKSPACE_CLIENT,
  REVERT_HUNK_SERVICE,
} from "./identifiers";
import { revertHunkContent } from "./revertHunk";

export { REVERT_HUNK_SERVICE };

export interface CodeReviewWorkspaceClient {
  getFileAtHead(
    directoryPath: string,
    filePath: string,
  ): Promise<string | null>;
  readRepoFile(repoPath: string, filePath: string): Promise<string | null>;
  writeRepoFile(
    repoPath: string,
    filePath: string,
    content: string,
  ): Promise<void>;
}

export interface RevertHunkInput {
  repoPath: string;
  filePath: string;
  hunkIndex: number;
}

export interface OptimisticRevertInput {
  repoPath: string;
  filePath: string;
  hunkIndex: number;
  fileDiff: FileDiffMetadata;
}

export interface OptimisticRevertCallbacks {
  onOptimisticApply(fileDiff: FileDiffMetadata): void;
  onRollback(): void;
}

@injectable()
export class RevertHunkService {
  constructor(
    @inject(CODE_REVIEW_WORKSPACE_CLIENT)
    private readonly workspace: CodeReviewWorkspaceClient,
  ) {}

  async revertHunk(input: RevertHunkInput): Promise<void> {
    const { repoPath, filePath, hunkIndex } = input;

    const [originalContent, modifiedContent] = await Promise.all([
      this.workspace.getFileAtHead(repoPath, filePath),
      this.workspace.readRepoFile(repoPath, filePath),
    ]);

    const newContent = revertHunkContent(
      filePath,
      originalContent ?? "",
      modifiedContent ?? "",
      hunkIndex,
    );

    await this.workspace.writeRepoFile(repoPath, filePath, newContent);
  }

  async revertHunkOptimistic(
    input: OptimisticRevertInput,
    callbacks: OptimisticRevertCallbacks,
  ): Promise<boolean> {
    const { repoPath, filePath, hunkIndex, fileDiff } = input;

    callbacks.onOptimisticApply(
      diffAcceptRejectHunk(fileDiff, hunkIndex, "reject"),
    );

    try {
      await this.revertHunk({ repoPath, filePath, hunkIndex });
      return true;
    } catch {
      callbacks.onRollback();
      return false;
    }
  }
}
