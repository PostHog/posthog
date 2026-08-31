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
import { isOnceOffSchedule } from "../loopScheduleRRule";
import { loopsKeys } from "./loopsKeys";
import { useLoopsClient } from "./useLoopsClient";
import { useWorkflowsClient } from "./useWorkflowsClient";

/** hog_flows-loops query keys that don't live in `loopsKeys` (which is Loops-API-specific).
 * Kept in one place so every mutation invalidates the same set. */
const workflowsLoopsKeys = {
  list: (projectId: string | null) => ["workflows-loops", "list", projectId],
  detail: (projectId: string | null, loopId: string) => [
    "workflows-loops",
    "detail",
    projectId,
    loopId,
  ],
  raw: (projectId: string | null, loopId: string) => [
    "workflows-loops",
    "raw",
    projectId,
    loopId,
  ],
  runs: (loopId: string) => ["workflows-loops", "runs", loopId],
};

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
        if (!scheduleWrite) return hogFlowToLoop(flow, null);
        try {
          const schedule = await createHogFlowSchedule(
            workflowsClient.client,
            workflowsClient.projectId,
            flow.id,
            scheduleWrite,
          );
          return hogFlowToLoop(flow, schedule);
        } catch (error) {
          // The flow already exists without a schedule at this point — an enabled loop that can
          // never fire, and every retry would create another. Roll it back rather than leave it.
          try {
            await destroyHogFlow(
              workflowsClient.client,
              workflowsClient.projectId,
              flow.id,
            );
          } catch {
            // The flow is orphaned; surfacing the original schedule error still tells the user
            // the create failed, which is the actionable half of this.
          }
          throw error;
        }
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
          ? workflowsLoopsKeys.list(workflowsClient?.projectId ?? null)
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
        // Re-anchoring an unchanged schedule to "now" can clear a due-but-unfired occurrence on
        // the backend (it recomputes next_run_at from the new starts_at) — so skip the write
        // entirely when the timing hasn't actually changed, rather than resending it every save.
        const scheduleUnchanged =
          !!scheduleWrite &&
          !!existingSchedule &&
          scheduleWrite.rrule === existingSchedule.rrule &&
          scheduleWrite.timezone === existingSchedule.timezone &&
          (isOnceOffSchedule(scheduleWrite.rrule)
            ? scheduleWrite.starts_at === existingSchedule.starts_at
            : true);
        const schedule = scheduleUnchanged
          ? existingSchedule
          : scheduleWrite
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
          ? workflowsLoopsKeys.detail(
              workflowsClient?.projectId ?? null,
              loopId,
            )
          : loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
        loop,
      );
    },
    onSettled: () => {
      // Runs on both success and failure: the flow PATCH can commit even when the follow-up
      // schedule write fails (see the mutationFn above), so the caches need refreshing either
      // way rather than only on a clean success.
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? workflowsLoopsKeys.list(workflowsClient?.projectId ?? null)
          : loopsKeys.list(loopsClient?.projectId ?? null),
      });
      if (hogFlowsEnabled) {
        void queryClient.invalidateQueries({
          queryKey: workflowsLoopsKeys.raw(
            workflowsClient?.projectId ?? null,
            loopId,
          ),
        });
      }
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
    onSuccess: (_data, loopId) => {
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? workflowsLoopsKeys.list(workflowsClient?.projectId ?? null)
          : loopsKeys.list(loopsClient?.projectId ?? null),
      });
      if (hogFlowsEnabled) {
        void queryClient.invalidateQueries({
          queryKey: workflowsLoopsKeys.raw(
            workflowsClient?.projectId ?? null,
            loopId,
          ),
        });
      }
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
          ? workflowsLoopsKeys.runs(loopId)
          : loopsKeys.runs(loopsClient?.projectId ?? null, loopId),
      });
      void queryClient.invalidateQueries({
        queryKey: hogFlowsEnabled
          ? workflowsLoopsKeys.detail(
              workflowsClient?.projectId ?? null,
              loopId,
            )
          : loopsKeys.detail(loopsClient?.projectId ?? null, loopId),
      });
    },
  });
}
