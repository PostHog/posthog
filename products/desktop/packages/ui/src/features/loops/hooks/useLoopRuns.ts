import { listHogFlowTasks } from "@posthog/api-client/hogFlowLoops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { useQuery } from "@tanstack/react-query";
import { taskToLoopRun } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export const RECENT_RUNS_LIMIT = 10;

/** The most recent runs for a loop, polled so the detail view stays live. */
export function useLoopRuns(loopId: string | undefined) {
  const loopsClient = useLoopsClient();
  const projectId = loopsClient?.projectId ?? null;

  return useQuery<LoopSchemas.LoopRun[]>({
    queryKey: loopsKeys.runs(projectId, loopId ?? ""),
    queryFn: async () => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      const page = await listHogFlowTasks(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        { limit: RECENT_RUNS_LIMIT },
      );
      return page.results.map(taskToLoopRun);
    },
    enabled: !!loopsClient && !!loopId,
    staleTime: 10_000,
    refetchInterval: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
