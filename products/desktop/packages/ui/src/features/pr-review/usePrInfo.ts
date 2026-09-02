import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

/** Full PR overview (title, body, state, branches, stats) from GitHub. */
export function usePrInfo(prUrl: string | null) {
  const trpc = useHostTRPC();
  return useQuery({
    ...trpc.git.getPrInfoByUrl.queryOptions({ prUrl: prUrl as string }),
    enabled: !!prUrl,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
    retry: 1,
  });
}
