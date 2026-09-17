import type { Schemas } from "@posthog/api-client/generated";
import { retrieveHogFlow } from "@posthog/api-client/hogFlowLoops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { hogFlowToLoop } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { type LoopsApiClient, useLoopsClient } from "./useLoopsClient";

function hogFlowQueryOptions(
  loopsClient: LoopsApiClient | null,
  loopId: string | undefined,
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
    enabled: !!loopsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  };
}

/** The workflow behind a loop, unmapped. Shares its cache entry with `useLoop`
 * so the detail page issues one request for both the loop and the shape check. */
export function useLoopHogFlow(loopId: string | undefined) {
  const loopsClient = useLoopsClient();
  return useQuery(hogFlowQueryOptions(loopsClient, loopId));
}

export function useLoop(loopId: string | undefined) {
  const loopsClient = useLoopsClient();
  const projectId = Number(loopsClient?.projectId);
  return useQuery({
    ...hogFlowQueryOptions(loopsClient, loopId),
    select: (flow: Schemas.HogFlow) => hogFlowToLoop(flow, { projectId }),
  });
}
