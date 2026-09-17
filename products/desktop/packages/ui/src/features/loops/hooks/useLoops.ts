import { listLoopHogFlows } from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { hogFlowToLoop } from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";

export function useLoops() {
  const loopsClient = useLoopsClient();
  return useQuery({
    queryKey: loopsKeys.hogFlowList(loopsClient?.projectId ?? null),
    queryFn: async (): Promise<LoopSchemas.Loop[]> => {
      if (!loopsClient) throw new Error("Not authenticated");
      const page = await listLoopHogFlows(
        loopsClient.client,
        loopsClient.projectId,
      );
      const projectId = Number(loopsClient.projectId);
      // The list endpoint returns archived workflows too. They would map to
      // paused loops whose Resume sets them active instead of restoring them.
      return page.results
        .filter((flow) => flow.status !== "archived")
        .map((flow) => hogFlowToLoop(flow, { projectId }));
    },
    enabled: !!loopsClient,
    staleTime: 30_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
