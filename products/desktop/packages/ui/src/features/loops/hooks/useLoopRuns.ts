import { listHogFlowTasks } from "@posthog/api-client/hogFlowLoops";
import { type LoopSchemas, listLoopRuns } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { useQuery } from "@tanstack/react-query";
import { taskToLoopRun } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export const RECENT_RUNS_LIMIT = 10;

/** The most recent runs for a loop, polled so the detail view stays live. */
export function useLoopRuns(loopId: string | undefined) {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const projectId = loopsClient?.projectId ?? null;

  const loopsApi = useQuery<
    LoopSchemas.LoopRunPage,
    Error,
    LoopSchemas.LoopRun[]
  >({
    queryKey: loopsKeys.runs(projectId, loopId ?? ""),
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
    enabled: !hogFlows && !!loopsClient && !!loopId,
    staleTime: 10_000,
    refetchInterval: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });

  // Run history for a workflow-backed loop is the tasks the workflow created.
  const workflow = useQuery<LoopSchemas.LoopRun[]>({
    queryKey: loopsKeys.hogFlowRuns(projectId, loopId ?? ""),
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
    enabled: hogFlows && !!loopsClient && !!loopId,
    staleTime: 10_000,
    refetchInterval: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });

  return hogFlows ? workflow : loopsApi;
}
