import { type LoopSchemas, listLoopRuns } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export const RECENT_RUNS_LIMIT = 10;

/** The most recent runs for a loop, polled so the detail view stays live. */
export function useLoopRuns(loopId: string | undefined) {
  const loopsClient = useLoopsClient();

  return useQuery<LoopSchemas.LoopRunPage, Error, LoopSchemas.LoopRun[]>({
    queryKey: loopsKeys.runs(loopsClient?.projectId ?? null, loopId ?? ""),
    queryFn: async () => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      return await listLoopRuns(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        { limit: RECENT_RUNS_LIMIT },
      );
    },
    select: (page) => page.results.slice(0, RECENT_RUNS_LIMIT),
    enabled: !!loopsClient && !!loopId,
    staleTime: 10_000,
    refetchInterval: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
