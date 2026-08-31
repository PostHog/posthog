import { type LoopSchemas, listLoops } from "@posthog/api-client/loops";
import {
  isLoopShapedHogFlow,
  listHogFlows,
} from "@posthog/api-client/workflows";
import { LOOPS_HOG_FLOWS_FLAG } from "@posthog/shared";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useQuery } from "@tanstack/react-query";
import { hogFlowMinimalToLoop } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { type LoopsApiClient, useLoopsClient } from "./useLoopsClient";
import {
  useWorkflowsClient,
  type WorkflowsApiClient,
} from "./useWorkflowsClient";

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

/** hog_flows-backed equivalent of `loopsPageQueryOptions`: lists every workflow and keeps only
 * the ones this feature would recognize as a loop (see `isLoopShapedHogFlow`) — a workflow built
 * or edited in the real Workflows editor isn't a loop this feature can show here. */
function hogFlowLoopsQueryOptions(
  workflowsClient: WorkflowsApiClient | null,
  enabled: boolean,
) {
  return {
    queryKey: [
      "workflows-loops",
      "list",
      workflowsClient?.projectId ?? null,
    ] as const,
    queryFn: async (): Promise<LoopSchemas.Loop[]> => {
      if (!workflowsClient) throw new Error("Not authenticated");
      const page = await listHogFlows(
        workflowsClient.client,
        workflowsClient.projectId,
        {
          limit: LOOPS_LIST_LIMIT,
        },
      );
      return page.results.filter(isLoopShapedHogFlow).map(hogFlowMinimalToLoop);
    },
    enabled: enabled && !!workflowsClient,
    staleTime: 30_000,
    meta: AUTH_SCOPED_QUERY_META,
  };
}

export function useLoops() {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();

  const legacy = useQuery({
    ...loopsPageQueryOptions(loopsClient, !hogFlowsEnabled),
    select: (page: LoopSchemas.PaginatedLoopList) => page.results,
  });
  const hogFlows = useQuery(
    hogFlowLoopsQueryOptions(workflowsClient, hogFlowsEnabled),
  );

  return hogFlowsEnabled ? hogFlows : legacy;
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

export function useLoopLimits(): LoopLimits | null {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const { data } = useQuery({
    ...loopsPageQueryOptions(loopsClient, !hogFlowsEnabled),
    select: (page: LoopSchemas.PaginatedLoopList): LoopLimits => ({
      max: page.max_loops_per_team,
      used: page.total_loop_count,
      atLimit: page.total_loop_count >= page.max_loops_per_team,
    }),
  });
  // HogFlows have no per-project loop cap yet.
  return hogFlowsEnabled ? null : (data ?? null);
}
