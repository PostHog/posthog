import { listLoopHogFlows } from "@posthog/api-client/hogFlowLoops";
import { type LoopSchemas, listLoops } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { useQuery } from "@tanstack/react-query";
import { hogFlowToLoop } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { type LoopsApiClient, useLoopsClient } from "./useLoopsClient";

const LOOPS_LIST_LIMIT = 100;

/** Shared query for the loops list page. Both `useLoops` (the loop rows) and `useLoopLimits`
 * (the per-project cap) read from this single fetch via `select`, so the cap the backend serves
 * stays in lockstep with the list and there's no second request. */
function loopsPageQueryOptions(
  loopsClient: LoopsApiClient | null,
  enabled: boolean,
) {
  return {
    queryKey: loopsKeys.list(loopsClient?.projectId ?? null),
    queryFn: async (): Promise<LoopSchemas.PaginatedLoopList> => {
      if (!loopsClient) throw new Error("Not authenticated");
      return listLoops(loopsClient.client, loopsClient.projectId, {
        limit: LOOPS_LIST_LIMIT,
      });
    },
    enabled: enabled && !!loopsClient,
    staleTime: 30_000,
    meta: AUTH_SCOPED_QUERY_META,
  };
}

function hogFlowLoopsQueryOptions(
  loopsClient: LoopsApiClient | null,
  enabled: boolean,
) {
  return {
    queryKey: loopsKeys.hogFlowList(loopsClient?.projectId ?? null),
    queryFn: async (): Promise<LoopSchemas.Loop[]> => {
      if (!loopsClient) throw new Error("Not authenticated");
      const page = await listLoopHogFlows(
        loopsClient.client,
        loopsClient.projectId,
      );
      const projectId = Number(loopsClient.projectId);
      return page.results.map((flow) => hogFlowToLoop(flow, { projectId }));
    },
    enabled: enabled && !!loopsClient,
    staleTime: 30_000,
    meta: AUTH_SCOPED_QUERY_META,
  };
}

export function useLoops() {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const loopsApi = useQuery({
    ...loopsPageQueryOptions(loopsClient, !hogFlows),
    select: (page: LoopSchemas.PaginatedLoopList) => page.results,
  });
  const workflows = useQuery(hogFlowLoopsQueryOptions(loopsClient, hogFlows));
  return hogFlows ? workflows : loopsApi;
}

/** The per-project loop cap, straight from the backend so the frontend never hardcodes it. */
export interface LoopLimits {
  /** Hard cap on non-deleted loops in this project. */
  max: number;
  /** Current non-deleted loops counted against `max`. */
  used: number;
  /** True when creating another loop would be rejected with a 429. */
  atLimit: boolean;
}

/** Null while loading, and always null for workflow-backed loops: workflows
 * cap task creation per run instead of capping how many loops exist. */
export function useLoopLimits(): LoopLimits | null {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const { data } = useQuery({
    ...loopsPageQueryOptions(loopsClient, !hogFlows),
    select: (page: LoopSchemas.PaginatedLoopList): LoopLimits => ({
      max: page.max_loops_per_team,
      used: page.total_loop_count,
      atLimit: page.total_loop_count >= page.max_loops_per_team,
    }),
  });
  return data ?? null;
}
