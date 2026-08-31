import { type LoopSchemas, retrieveLoop } from "@posthog/api-client/loops";
import { retrieveHogFlow } from "@posthog/api-client/workflows";
import { LOOPS_HOG_FLOWS_FLAG } from "@posthog/shared";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useQuery } from "@tanstack/react-query";
import {
  hogFlowToLoop,
  isDecompilableLoopHogFlow,
} from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";
import { useWorkflowsClient } from "./useWorkflowsClient";

export function useLoop(loopId: string | undefined) {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();

  const legacy = useQuery<LoopSchemas.Loop>({
    queryKey: loopsKeys.detail(loopsClient?.projectId ?? null, loopId ?? ""),
    queryFn: async () => {
      if (!loopsClient || !loopId) throw new Error("Not authenticated");
      return await retrieveLoop(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
      );
    },
    enabled: !hogFlowsEnabled && !!loopsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });

  const hogFlow = useQuery<LoopSchemas.Loop>({
    queryKey: [
      "workflows-loops",
      "detail",
      workflowsClient?.projectId ?? null,
      loopId ?? "",
    ],
    queryFn: async () => {
      if (!workflowsClient || !loopId) throw new Error("Not authenticated");
      const flow = await retrieveHogFlow(
        workflowsClient.client,
        workflowsClient.projectId,
        loopId,
      );
      // A workflow this feature didn't build (or hand-edited elsewhere since) isn't a loop this
      // feature can show or edit safely — failing here keeps Save/Delete from acting on a
      // resource whose real shape they'd silently destroy. See `isDecompilableLoopHogFlow`.
      if (!isDecompilableLoopHogFlow(flow, flow.schedules)) {
        throw new Error("This workflow isn't editable as a loop.");
      }
      return hogFlowToLoop(flow, flow.schedules[0] ?? null);
    },
    enabled: hogFlowsEnabled && !!workflowsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });

  return hogFlowsEnabled ? hogFlow : legacy;
}
