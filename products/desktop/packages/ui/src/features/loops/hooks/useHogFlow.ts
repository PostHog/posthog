import {
  retrieveHogFlow,
  type WorkflowSchemas,
} from "@posthog/api-client/workflows";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { useWorkflowsClient } from "./useWorkflowsClient";

/**
 * The raw HogFlow behind a loop, only needed where `useLoop`'s `Loop`-shaped facade loses
 * information the `Loop` wire type has no field for — `LoopForm` initializing its edit state
 * needs `skillNames`, which only `hogFlowToFormValues` (fed by the raw flow) can produce. Every
 * other read (list rows, the detail view's read-only summary) goes through `useLoop`.
 */
export function useHogFlow(loopId: string | undefined, enabled: boolean) {
  const workflowsClient = useWorkflowsClient();

  return useQuery<{
    flow: WorkflowSchemas.HogFlow;
    schedule: WorkflowSchemas.HogFlowSchedule | null;
  }>({
    queryKey: [
      "workflows-loops",
      "raw",
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
      return { flow, schedule: flow.schedules[0] ?? null };
    },
    enabled: enabled && !!workflowsClient && !!loopId,
    staleTime: 15_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}
