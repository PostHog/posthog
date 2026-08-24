import {
  type DiffStats,
  deriveIsCloud,
  selectTaskDiffStats,
} from "@posthog/core/code-review/selectTaskDiffStats";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import {
  useLocalBranchChangedFiles,
  usePrChangedFiles,
} from "../../git-interaction/useGitQueries";
import { computeDiffStats } from "../../git-interaction/utils/diffStats";
import { useCwd } from "../../sidebar/useCwd";
import { useCloudChangedFiles } from "../../task-detail/hooks/useCloudChangedFiles";
import { useWorkspace } from "../../workspace/useWorkspace";
import { useEffectiveDiffSource } from "./useEffectiveDiffSource";

export function useTaskDiffSummaryStats(task: Task): DiffStats {
  const taskId = task.id;
  const workspace = useWorkspace(taskId);
  const isCloud = deriveIsCloud(workspace?.mode, task.latest_run?.environment);

  const { reviewFiles } = useCloudChangedFiles(taskId, task, isCloud);

  const repoPath = useCwd(taskId);
  const {
    effectiveSource,
    linkedBranch,
    prUrl,
    diffStats: localDiffStats,
  } = useEffectiveDiffSource(taskId);

  const { data: branchFiles } = useLocalBranchChangedFiles(
    !isCloud && effectiveSource === "branch" ? (repoPath ?? null) : null,
    !isCloud && effectiveSource === "branch" ? linkedBranch : null,
  );
  const { data: prFiles } = usePrChangedFiles(
    !isCloud && effectiveSource === "pr" ? prUrl : null,
  );

  return useMemo<DiffStats>(
    () =>
      selectTaskDiffStats({
        isCloud,
        effectiveSource,
        reviewFiles,
        branchFiles,
        prFiles,
        localDiffStats,
        computeStats: computeDiffStats,
      }),
    [
      isCloud,
      reviewFiles,
      effectiveSource,
      branchFiles,
      prFiles,
      localDiffStats,
    ],
  );
}
