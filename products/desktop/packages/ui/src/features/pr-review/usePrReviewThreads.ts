import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/** Inline review threads (code comments) on a PR. */
export function usePrReviewThreads(prUrl: string | null) {
  const trpc = useHostTRPC();
  return useQuery({
    ...trpc.git.getPrReviewComments.queryOptions({ prUrl: prUrl as string }),
    enabled: !!prUrl,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: 1,
  });
}
