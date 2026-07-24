import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/** Conversation (issue) comments on a PR. */
export function usePrComments(prUrl: string | null) {
  const trpc = useHostTRPC();
  return useQuery({
    ...trpc.git.getPrComments.queryOptions({ prUrl: prUrl as string }),
    enabled: !!prUrl,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: 1,
  });
}
