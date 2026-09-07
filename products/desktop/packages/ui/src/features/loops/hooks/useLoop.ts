import type { Schemas } from "@posthog/api-client/generated";
import { retrieveHogFlow } from "@posthog/api-client/hogFlowLoops";
import { type LoopSchemas, retrieveLoop } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import { useQuery } from "@tanstack/react-query";
import { hogFlowToLoop } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { type LoopsApiClient, useLoopsClient } from "./useLoopsClient";

function hogFlowQueryOptions(
  loopsClient: LoopsApiClient | null,
  loopId: string | undefined,
  enabled: boolean,
) {
  return {
    queryKey: loopsKeys.hogFlow(loopsClient?.projectId ?? null, loopId ?? ""),
    queryFn: async (): Promise<Schemas.HogFlow> => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      return await retrieveHogFlow(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
      );
    },
    enabled: enabled && !!loopsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  };
}

/** The workflow behind a loop, unmapped. Shares its cache entry with `useLoop`
 * so the detail page issues one request for both the loop and the shape check. */
export function useLoopHogFlow(loopId: string | undefined) {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  return useQuery(hogFlowQueryOptions(loopsClient, loopId, hogFlows));
}

export function useLoop(loopId: string | undefined) {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const projectId = Number(loopsClient?.projectId);

  const loopsApi = useQuery<LoopSchemas.Loop>({
    queryKey: loopsKeys.detail(loopsClient?.projectId ?? null, loopId ?? ""),
    queryFn: async () => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      return await retrieveLoop(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
      );
    },
    enabled: !hogFlows && !!loopsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const workflow = useQuery({
    ...hogFlowQueryOptions(loopsClient, loopId, hogFlows),
    select: (flow: Schemas.HogFlow) => hogFlowToLoop(flow, { projectId }),
  });
  return hogFlows ? workflow : loopsApi;
}
