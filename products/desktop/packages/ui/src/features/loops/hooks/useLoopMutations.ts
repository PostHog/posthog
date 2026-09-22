import type { Schemas } from "@posthog/api-client/generated";
import { deleteHogFlow } from "@posthog/api-client/hogFlowLoops";
import {
  createLoop,
  destroyLoop,
  type LoopSchemas,
  partialUpdateLoop,
  runLoop,
} from "@posthog/api-client/loops";
import { useLoopsHogFlowsEnabled } from "@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled";
import {
  type QueryClient,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { LoopFormValues } from "../loopFormTypes";
import { formValuesToHogFlowWrite, hogFlowToLoop } from "../loopHogFlowMapping";
import {
  createLoopHogFlow,
  LoopScheduleSaveError,
  runLoopHogFlow,
  setLoopHogFlowEnabled,
  updateLoopHogFlow,
} from "../loopHogFlowWrites";
import { loopsKeys } from "./loopsKeys";
import { type LoopsApiClient, useLoopsClient } from "./useLoopsClient";

function invalidateLoopLists(
  queryClient: QueryClient,
  projectId: string | null,
): void {
  void queryClient.invalidateQueries({ queryKey: loopsKeys.list(projectId) });
  void queryClient.invalidateQueries({
    queryKey: loopsKeys.hogFlowList(projectId),
  });
}

/** Stores a saved workflow so the detail page reflects the write at once. */
function applyHogFlowToCache(
  queryClient: QueryClient,
  loopsClient: LoopsApiClient,
  flow: Schemas.HogFlow,
): LoopSchemas.Loop {
  queryClient.setQueryData(
    loopsKeys.hogFlow(loopsClient.projectId, flow.id),
    flow,
  );
  invalidateLoopLists(queryClient, loopsClient.projectId);
  return hogFlowToLoop(flow, { projectId: Number(loopsClient.projectId) });
}

export function useCreateLoop() {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, LoopSchemas.LoopWrite>({
    mutationFn: async (body) => {
      if (!loopsClient) throw new Error("Not authenticated");
      return await createLoop(loopsClient.client, loopsClient.projectId, body);
    },
    onSuccess: () => {
      invalidateLoopLists(queryClient, loopsClient?.projectId ?? null);
    },
  });
}

/** Creates a workflow-backed loop from the form. `enabled` picks between a
 * live workflow and a draft, since the form has no separate enable step. */
export function useCreateLoopHogFlow() {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<
    LoopSchemas.Loop,
    Error,
    { values: LoopFormValues; enabled: boolean }
  >({
    mutationFn: async ({ values, enabled }) => {
      if (!loopsClient) throw new Error("Not authenticated");
      const flow = await createLoopHogFlow(
        loopsClient.client,
        loopsClient.projectId,
        formValuesToHogFlowWrite(values, { enabled }),
      );
      return applyHogFlowToCache(queryClient, loopsClient, flow);
    },
  });
}

/** Partial updates against the loop's lifecycle fields. For a workflow-backed
 * loop only `enabled` applies; content edits go through `useUpdateLoopHogFlow`. */
export function useUpdateLoop(loopId: string) {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, LoopSchemas.PatchedLoop>({
    mutationFn: async (body) => {
      if (!loopsClient) throw new Error("Not authenticated");
      if (!hogFlows) {
        return await partialUpdateLoop(
          loopsClient.client,
          loopsClient.projectId,
          loopId,
          body,
        );
      }
      if (typeof body.enabled !== "boolean") {
        throw new Error(
          "Only the enabled state can be patched on a workflow-backed loop.",
        );
      }
      const flow = await setLoopHogFlowEnabled(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        body.enabled,
      );
      return applyHogFlowToCache(queryClient, loopsClient, flow);
    },
    onSuccess: (loop) => {
      if (hogFlows) return;
      queryClient.setQueryData(
        loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
        loop,
      );
      invalidateLoopLists(queryClient, loopsClient?.projectId ?? null);
    },
  });
}

/** Saves the whole form onto an existing workflow-backed loop. Needs the
 * current workflow so the schedule row can be reconciled rather than rewritten. */
export function useUpdateLoopHogFlow(loopId: string) {
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<
    LoopSchemas.Loop,
    Error,
    { values: LoopFormValues; existing: Schemas.HogFlow }
  >({
    mutationFn: async ({ values, existing }) => {
      if (!loopsClient) throw new Error("Not authenticated");
      try {
        const flow = await updateLoopHogFlow(
          loopsClient.client,
          loopsClient.projectId,
          existing,
          formValuesToHogFlowWrite(values, {
            enabled: existing.status === "active",
            existing,
          }),
        );
        return applyHogFlowToCache(queryClient, loopsClient, flow);
      } catch (error) {
        // The graph is live with a new `updated_at`; caching it keeps the
        // retry's `base_updated_at` current instead of refused as stale.
        if (error instanceof LoopScheduleSaveError) {
          applyHogFlowToCache(queryClient, loopsClient, error.flow);
        }
        throw error;
      }
    },
    onSettled: () => {
      // A partial failure (graph saved, schedule not) leaves the cache behind
      // the server; refetching the flow shows what actually stuck.
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.hogFlow(loopsClient?.projectId ?? null, loopId),
      });
    },
  });
}

export function useDeleteLoop() {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (loopId) => {
      if (!loopsClient) throw new Error("Not authenticated");
      if (hogFlows) {
        await deleteHogFlow(loopsClient.client, loopsClient.projectId, loopId);
        return;
      }
      await destroyLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      invalidateLoopLists(queryClient, loopsClient?.projectId ?? null);
    },
  });
}

export function useRunLoop(loopId: string) {
  const hogFlows = useLoopsHogFlowsEnabled();
  const loopsClient = useLoopsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.LoopFireRun, Error, void>({
    mutationFn: async () => {
      if (!loopsClient) throw new Error("Not authenticated");
      if (hogFlows) {
        return await runLoopHogFlow(
          loopsClient.client,
          loopsClient.projectId,
          loopId,
        );
      }
      return await runLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      const projectId = loopsClient?.projectId ?? null;
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.runs(projectId, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.hogFlowRuns(projectId, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.detail(projectId, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: loopsKeys.hogFlow(projectId, loopId),
      });
    },
  });
}
