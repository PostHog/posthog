import {
  type CreateBranchResult,
  createBranch as createBranchCore,
} from "@posthog/core/git-interaction/branchCreation";
import { invalidateGitBranchQueries } from "../gitCacheKeys";

export {
  type BranchNameInputState,
  type CreateBranchResult,
  getBranchNameInputState,
} from "@posthog/core/git-interaction/branchCreation";

interface BranchCreator {
  createBranch(repoPath: string, branchName: string): Promise<void>;
}

interface CreateBranchInput {
  writeClient: BranchCreator;
  repoPath?: string;
  rawBranchName: string;
}

export async function createBranch(
  input: CreateBranchInput,
): Promise<CreateBranchResult> {
  const result = await createBranchCore(input);
  if (result.success && input.repoPath) {
    invalidateGitBranchQueries(input.repoPath);
  }
  return result;
}
