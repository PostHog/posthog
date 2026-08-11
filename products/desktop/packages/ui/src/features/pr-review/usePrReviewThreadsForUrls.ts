import { useHostTRPC } from "@posthog/host-router/react";
import type { PrReviewThread } from "@posthog/shared";
import { useQueries } from "@tanstack/react-query";

/** Inline review threads for several PRs at once. See `usePrCommentsForUrls`. */
export function usePrReviewThreadsForUrls(prUrls: string[]) {
  const trpc = useHostTRPC();
  return useQueries({
    queries: prUrls.map((prUrl) => ({
      ...trpc.git.getPrReviewComments.queryOptions({ prUrl }),
      staleTime: 30_000,
      placeholderData: (prev: PrReviewThread[] | undefined) => prev,
      retry: 1,
    })),
    combine: (results) => ({
      byUrl: prUrls.map(
        (prUrl, index) =>
          [prUrl, results[index]?.data ?? []] as [string, PrReviewThread[]],
      ),
      isLoading: results.some((result) => result.isLoading),
      isError: results.some((result) => result.isError),
    }),
  });
}
