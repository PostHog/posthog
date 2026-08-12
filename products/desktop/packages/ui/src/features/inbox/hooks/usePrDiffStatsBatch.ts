import type { PrDiffStats } from "@posthog/core/git/router-schemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

export type { PrDiffStats };

/**
 * Single-request batch fetch of PR diff stats (additions/deletions/changedFiles)
 * across many PR URLs. Backed by `git.getPrDiffStatsBatch`, which alias-batches
 * the lookups into one GitHub GraphQL request (chunked internally).
 */
export function usePrDiffStatsBatch(prUrls: string[]) {
  const trpc = useHostTRPC();

  // Sort + dedupe so the query key stays stable when upstream list order
  // shifts but membership doesn't.
  const sortedUrls = useMemo(
    () => Array.from(new Set(prUrls.filter(Boolean))).sort(),
    [prUrls],
  );

  return useQuery(
    trpc.git.getPrDiffStatsBatch.queryOptions(
      { prUrls: sortedUrls },
      {
        enabled: sortedUrls.length > 0,
        staleTime: 5 * 60_000,
        // Each distinct visible URL set becomes a distinct query entry, and
        // filtering / scope changes can churn through many. Bound the cache.
        gcTime: 10 * 60_000,
        // gh stats change slowly and the API is rate-limited.
        refetchOnWindowFocus: false,
        retry: 1,
      },
    ),
  );
}
