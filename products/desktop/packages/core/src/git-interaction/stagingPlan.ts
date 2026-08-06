import type { ChangedFile } from "@posthog/shared/domain-types";
import type { GitStagingContext } from "./gitInteractionService";

export interface StagingPlan {
  stagingContext: GitStagingContext;
  stagedOnly: boolean;
}

export function deriveStagingPlan(
  stagedFiles: ChangedFile[],
  unstagedFiles: ChangedFile[],
  commitAll: boolean,
): StagingPlan {
  const hasMixedStaging = stagedFiles.length > 0 && unstagedFiles.length > 0;
  const stagedOnly = hasMixedStaging && !commitAll;
  return {
    stagedOnly,
    stagingContext: {
      staged_file_count: stagedFiles.length,
      unstaged_file_count: unstagedFiles.length,
      commit_all: commitAll,
      staged_only: stagedOnly,
    },
  };
}

export interface CreatePrPlan {
  needsBranch: boolean;
  needsCommit: boolean;
  commitAll: boolean;
}

export function deriveCreatePrPlan(input: {
  isFeatureBranch: boolean;
  prExists: boolean;
  hasChanges: boolean;
  stagedFileCount: number;
  unstagedFileCount: number;
}): CreatePrPlan {
  const hasMixedStaging =
    input.stagedFileCount > 0 && input.unstagedFileCount > 0;
  return {
    needsBranch: !input.isFeatureBranch || input.prExists,
    needsCommit: input.hasChanges,
    commitAll: !hasMixedStaging,
  };
}
