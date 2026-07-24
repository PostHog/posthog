import {
  type ResolvedDiffSource,
  resolveDiffSource,
} from "@posthog/core/code-review/resolveDiffSource";
import { EMPTY_DIFF_STATS } from "@posthog/core/code-review/selectTaskDiffStats";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useDiffViewerStore } from "../../code-editor/diffViewerStore";
import { useDiffStats } from "../../diff-stats/useDiffStats";
import { useTaskPrUrl } from "../../git-interaction/useTaskPrUrl";
import type { DiffStats } from "../../git-interaction/utils/diffStats";
import { useCwd } from "../../sidebar/useCwd";
import { useWorkspace } from "../../workspace/useWorkspace";

export interface EffectiveDiffSource {
  effectiveSource: ResolvedDiffSource;
  prUrl: string | null;
  linkedBranch: string | null;
  defaultBranch: string | null;
  repoSlug: string | null;
  branchSourceAvailable: boolean;
  prSourceAvailable: boolean;
  diffStats: DiffStats;
}

export function useEffectiveDiffSource(taskId: string): EffectiveDiffSource {
  const trpc = useHostTRPC();
  const repoPath = useCwd(taskId);
  const workspace = useWorkspace(taskId);
  const linkedBranch = workspace?.linkedBranch ?? null;

  const configured = useDiffViewerStore((s) => s.diffSource[taskId] ?? null);

  const enabled = !!repoPath;

  const { data: syncStatus } = useQuery(
    trpc.git.getGitSyncStatus.queryOptions(
      { directoryPath: repoPath as string },
      { enabled, staleTime: 30_000 },
    ),
  );

  const { data: repoInfo } = useQuery(
    trpc.git.getGitRepoInfo.queryOptions(
      { directoryPath: repoPath as string },
      { enabled, staleTime: 60_000 },
    ),
  );

  const { data: diffStats = EMPTY_DIFF_STATS } = useDiffStats(repoPath ?? null);

  const aheadOfDefault = syncStatus?.aheadOfDefault ?? 0;
  const defaultBranch = repoInfo?.defaultBranch ?? null;
  const hasLocalChanges = diffStats.filesChanged > 0;
  const branchSourceAvailable = !!linkedBranch && aheadOfDefault > 0;

  const prUrl = useTaskPrUrl(taskId, workspace?.mode === "cloud");
  const prSourceAvailable = !!prUrl;

  const repoSlug = repoInfo
    ? `${repoInfo.organization}/${repoInfo.repository}`
    : null;

  const effectiveSource = resolveDiffSource({
    configured,
    hasLocalChanges,
    linkedBranch,
    aheadOfDefault,
    prSourceAvailable,
  });

  return {
    effectiveSource,
    prUrl,
    linkedBranch,
    defaultBranch,
    repoSlug,
    branchSourceAvailable,
    prSourceAvailable,
    diffStats,
  };
}
