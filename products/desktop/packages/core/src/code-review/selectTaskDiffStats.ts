import type { ChangedFile } from "@posthog/shared/domain-types";
import type { ResolvedDiffSource } from "./types";

export interface DiffStats {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
}

export const EMPTY_DIFF_STATS: DiffStats = {
  filesChanged: 0,
  linesAdded: 0,
  linesRemoved: 0,
};

export interface SelectTaskDiffStatsInput {
  isCloud: boolean;
  effectiveSource: ResolvedDiffSource;
  reviewFiles: ChangedFile[];
  branchFiles: ChangedFile[] | undefined;
  prFiles: ChangedFile[] | undefined;
  localDiffStats: DiffStats;
  computeStats: (files: ChangedFile[]) => DiffStats;
}

export function selectTaskDiffStats({
  isCloud,
  effectiveSource,
  reviewFiles,
  branchFiles,
  prFiles,
  localDiffStats,
  computeStats,
}: SelectTaskDiffStatsInput): DiffStats {
  if (isCloud) return computeStats(reviewFiles);
  if (effectiveSource === "branch") {
    return branchFiles ? computeStats(branchFiles) : EMPTY_DIFF_STATS;
  }
  if (effectiveSource === "pr") {
    return prFiles ? computeStats(prFiles) : EMPTY_DIFF_STATS;
  }
  return localDiffStats;
}

export function deriveIsCloud(
  workspaceMode: string | undefined,
  latestRunEnvironment: string | undefined,
): boolean {
  return workspaceMode === "cloud" || latestRunEnvironment === "cloud";
}
