import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/**
 * CI checks for a PR. Polls while the view is mounted and the window is
 * visible (TanStack pauses intervals for hidden documents by default), so a
 * running pipeline keeps updating without a manual refresh.
 */
export function usePrChecks(prUrl: string | null) {
  const trpc = useHostTRPC();
  return useQuery({
    ...trpc.git.getPrChecks.queryOptions({ prUrl: prUrl as string }),
    enabled: !!prUrl,
    staleTime: 10_000,
    refetchInterval: 15_000,
    placeholderData: (prev) => prev,
    retry: 1,
  });
}
