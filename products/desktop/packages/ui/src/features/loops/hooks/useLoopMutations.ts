import {
  createLoop,
  destroyLoop,
  type LoopSchemas,
  partialUpdateLoop,
  runLoop,
} from "@posthog/api-client/loops";
import {
  createHogFlow,
  createHogFlowSchedule,
  destroyHogFlow,
  partialUpdateHogFlow,
  partialUpdateHogFlowSchedule,
  runHogFlow,
  WorkflowsApiError,
} from "@posthog/api-client/workflows";
import { LOOPS_HOG_FLOWS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { formValuesToLoopWrite, type LoopFormValues } from "../loopFormTypes";
import {
  formValuesToHogFlowWrite,
  formValuesToScheduleWrite,
  hogFlowToLoop,
} from "../loopHogFlowMapping";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";
import { useWorkflowsClient } from "./useWorkflowsClient";

/** A HogFlow write always needs a status; a freshly created loop starts active unless its
 * (only) trigger was created disabled. */
function statusFor(values: LoopFormValues): "active" | "draft" {
  return values.triggers[0]?.enabled ? "active" : "draft";
}

export function useCreateLoop() {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, LoopFormValues>({
    mutationFn: async (values) => {
      if (hogFlowsEnabled) {
        if (!workflowsClient) throw new Error("Not authenticated");
        const flow = await createHogFlow(
          workflowsClient.client,
          workflowsClient.projectId,
          formValuesToHogFlowWrite(values, statusFor(values)),
        );
        const scheduleWrite = formValuesToScheduleWrite(values);
        const schedule = scheduleWrite
          ? await createHogFlowSchedule(
              workflowsClient.client,
              workflowsClient.projectId,
              flow.id,
              scheduleWrite,
            )
          : null;
        return hogFlowToLoop(flow, schedule);
      }
      if (!loopsClient) throw new Error("Not authenticated");
      return await createLoop(
        loopsClient.client,
        loopsClient.projectId,
        formValuesToLoopWrite(values),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? ["workflows-loops", "list"]
          : loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

/** Either a full form save, or the detail view's isolated "toggle enabled" switch — the latter
 * touches only the loop's status, never the rest of its config. */
export type UpdateLoopPayload =
  | { kind: "toggleEnabled"; enabled: boolean }
  | { kind: "save"; values: LoopFormValues };

export function useUpdateLoop(loopId: string) {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.Loop, Error, UpdateLoopPayload>({
    mutationFn: async (payload) => {
      if (hogFlowsEnabled) {
        if (!workflowsClient) throw new Error("Not authenticated");
        if (payload.kind === "toggleEnabled") {
          const flow = await partialUpdateHogFlow(
            workflowsClient.client,
            workflowsClient.projectId,
            loopId,
            { status: payload.enabled ? "active" : "draft" },
          );
          return hogFlowToLoop(flow, flow.schedules[0] ?? null);
        }

        const flow = await partialUpdateHogFlow(
          workflowsClient.client,
          workflowsClient.projectId,
          loopId,
          formValuesToHogFlowWrite(payload.values, statusFor(payload.values)),
        );
        const scheduleWrite = formValuesToScheduleWrite(payload.values);
        const existingSchedule = flow.schedules[0] ?? null;
        const schedule = scheduleWrite
          ? existingSchedule
            ? await partialUpdateHogFlowSchedule(
                workflowsClient.client,
                workflowsClient.projectId,
                loopId,
                existingSchedule.id,
                scheduleWrite,
              )
            : await createHogFlowSchedule(
                workflowsClient.client,
                workflowsClient.projectId,
                loopId,
                scheduleWrite,
              )
          : existingSchedule;
        return hogFlowToLoop(flow, schedule);
      }

      if (!loopsClient) throw new Error("Not authenticated");
      const body: LoopSchemas.PatchedLoop =
        payload.kind === "toggleEnabled"
          ? { enabled: payload.enabled }
          : formValuesToLoopWrite(payload.values);
      return await partialUpdateLoop(
        loopsClient.client,
        loopsClient.projectId,
        loopId,
        body,
      );
    },
    onSuccess: (loop) => {
      queryClient.setQueryData(
        hogFlowsEnabled
          ? [
              "workflows-loops",
              "detail",
              workflowsClient?.projectId ?? null,
              loopId,
            ]
          : loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
        loop,
      );
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? ["workflows-loops", "list"]
          : loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

export function useDeleteLoop() {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();
  const queryClient = useQueryClient();

  return useMutation<void, Error, string>({
    mutationFn: async (loopId) => {
      if (hogFlowsEnabled) {
        if (!workflowsClient) throw new Error("Not authenticated");
        await destroyHogFlow(
          workflowsClient.client,
          workflowsClient.projectId,
          loopId,
        );
        return;
      }
      if (!loopsClient) throw new Error("Not authenticated");
      await destroyLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? ["workflows-loops", "list"]
          : loopsKeys.list(loopsClient?.projectId ?? null),
      });
    },
  });
}

export function useRunLoop(loopId: string) {
  const hogFlowsEnabled = useFeatureFlag(LOOPS_HOG_FLOWS_FLAG);
  const loopsClient = useLoopsClient();
  const workflowsClient = useWorkflowsClient();
  const queryClient = useQueryClient();

  return useMutation<LoopSchemas.LoopFireRun, Error, void>({
    mutationFn: async () => {
      if (hogFlowsEnabled) {
        if (!workflowsClient) throw new Error("Not authenticated");
        try {
          await runHogFlow(
            workflowsClient.client,
            workflowsClient.projectId,
            loopId,
          );
        } catch (error) {
          // Unlike Loops' own dedup/rate-cap system, a hog_flows run either queues or fails
          // outright (e.g. "must be active") — there's no soft-reject reason to report, so this
          // surfaces as a thrown error for the caller's generic catch block instead of a
          // `LoopFireRun.reason`.
          throw new Error(
            error instanceof WorkflowsApiError
              ? (error.detail ?? error.message)
              : (error as Error).message,
          );
        }
        // The run is only queued at this point; the task it spawns doesn't exist yet, so there's
        // no task_id/task_run_id to report (unlike Loops' own synchronous fire).
        return {
          created: true,
          reason: "created",
          task_id: null,
          task_run_id: null,
        };
      }
      if (!loopsClient) throw new Error("Not authenticated");
      return await runLoop(loopsClient.client, loopsClient.projectId, loopId);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? ["workflows-loops", "runs", loopId]
          : loopsKeys.runs(loopsClient?.projectId ?? null, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? [
              "workflows-loops",
              "detail",
              workflowsClient?.projectId ?? null,
              loopId,
            ]
          : loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
      });
    },
  });
}
