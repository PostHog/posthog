import { usePrChangedFiles } from "@posthog/ui/features/git-interaction/useGitQueries";
import { computeDiffStats } from "@posthog/ui/features/git-interaction/utils/diffStats";
import { PrDiffIndicator } from "@posthog/ui/features/inbox/components/PrDiffIndicator";
import { usePrDiffStatsFromBatch } from "@posthog/ui/features/inbox/context/PrDiffStatsBatchContext";

interface PrDiffStatsProps {
  prUrl: string;
  /** Omit the loading skeleton – useful in compact list rows. */
  hideWhileLoading?: boolean;
}

/**
 * Renders the `+12 -3 (4 files)` adornment for a PR.
 *
 * Prefers the batched stats from `PrDiffStatsBatchContext` (one GraphQL
 * request for the whole list, mounted by `PullRequestsTab`). Falls back to
 * the per-PR `getPrChangedFiles` REST query only when there's no provider –
 * i.e. on the standalone detail page where there's no list to batch with.
 */
export function PrDiffStats({
  prUrl,
  hideWhileLoading = false,
}: PrDiffStatsProps) {
  const batchEntry = usePrDiffStatsFromBatch(prUrl);

  if (batchEntry.hasBatch) {
    if (batchEntry.stats) {
      return (
        <PrDiffIndicator
          added={batchEntry.stats.additions}
          removed={batchEntry.stats.deletions}
          files={batchEntry.stats.changedFiles}
        />
      );
    }
    if (hideWhileLoading || !batchEntry.isLoading) return null;
    return (
      <span
        className="inline-block h-3 w-12 shrink-0 animate-pulse rounded bg-(--gray-3)"
        aria-hidden
      />
    );
  }

  return (
    <PrDiffStatsStandalone prUrl={prUrl} hideWhileLoading={hideWhileLoading} />
  );
}

/** Per-PR query used when there's no surrounding batch provider (detail page). */
function PrDiffStatsStandalone({
  prUrl,
  hideWhileLoading,
}: {
  prUrl: string;
  hideWhileLoading: boolean;
}) {
  const { data, isLoading, isError } = usePrChangedFiles(prUrl);

  if (isLoading || !data) {
    if (hideWhileLoading || isError) {
      return null;
    }
    return (
      <span
        className="inline-block h-3 w-12 shrink-0 animate-pulse rounded bg-(--gray-3)"
        aria-hidden
      />
    );
  }

  const stats = computeDiffStats(data);
  return (
    <PrDiffIndicator
      added={stats.linesAdded}
      removed={stats.linesRemoved}
      files={stats.filesChanged}
    />
  );
}
