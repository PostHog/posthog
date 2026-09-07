import { EMPTY_DIFF_STATS } from "@posthog/core/code-review/selectTaskDiffStats";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export interface UseDiffStatsOptions {
  enabled?: boolean;
}

/**
 * Working-tree diff stats for the header badge / session chip.
 *
 * Deliberately reads the same `git.getDiffStats` query that `useGitQueries`
 * (the changes panel + PR button) and the diff panel rely on, so the numbers
 * share one cache entry and one fetch, and refresh off the same file-watcher
 * invalidation (`invalidateGitWorkingTreeQueries`). A separate transport with
 * its own poll interval used to back this and drifted out of sync with the
 * panel; keep it unified.
 */
export function useDiffStats(
  directoryPath: string | null,
  options: UseDiffStatsOptions = {},
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.git.getDiffStats.queryOptions(
      { directoryPath: directoryPath ?? "" },
      {
        enabled: (options.enabled ?? true) && !!directoryPath,
        staleTime: 30_000,
        // Plain value, not the `(prev) => prev` carry-over idiom: the header
        // badge's observer survives task switches without remounting, so
        // carrying data across query keys would show the previous repo's
        // numbers — indefinitely when the next task has no cwd and the query
        // stays disabled.
        placeholderData: EMPTY_DIFF_STATS,
      },
    ),
  );
}
