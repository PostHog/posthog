import type { ApiClient, Schemas } from "@posthog/api-client/generated";
import {
  createHogFlow,
  createHogFlowSchedule,
  deleteHogFlow,
  deleteHogFlowSchedule,
  patchHogFlow,
  runHogFlow,
  updateHogFlowSchedule,
} from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import type { LoopHogFlowWrite } from "./loopHogFlowMapping";
import { hogFlowScheduleMatches } from "./loopScheduleRRule";

/** The graph saved but the schedule row did not follow. The loop is live with
 * its old cadence (or none), so the person has to save again. */
export class LoopScheduleSaveError extends Error {
  readonly cause: unknown;

  constructor(cause: unknown) {
    super("Loop saved, but its schedule didn't update.");
    this.name = "LoopScheduleSaveError";
    this.cause = cause;
  }
}

/**
 * The request sequences behind saving a workflow-backed loop. A loop is a
 * workflow plus, for a schedule trigger, one schedule row; these keep the two
 * consistent when the second request fails.
 */

/**
 * Creates the workflow, then its schedule. If the schedule is rejected the
 * workflow is deleted again, so a failed save leaves nothing behind. Until the
 * schedule exists the workflow is inert: the scheduler only fires flows with an
 * active schedule row.
 */
export async function createLoopHogFlow(
  client: ApiClient,
  projectId: string,
  write: LoopHogFlowWrite,
): Promise<Schemas.HogFlow> {
  const flow = await createHogFlow(client, projectId, write.flow);
  if (!write.schedule) return flow;
  try {
    const schedule = await createHogFlowSchedule(
      client,
      projectId,
      flow.id,
      write.schedule,
    );
    return { ...flow, schedules: [schedule] };
  } catch (error) {
    try {
      await deleteHogFlow(client, projectId, flow.id);
    } catch {
      // The schedule rejection is the error worth reporting. A failed rollback
      // leaves an inert draft-like flow the person can delete from the list.
    }
    throw error;
  }
}

/**
 * Writes the graph, then reconciles the schedule row. The row is left alone
 * when it already matches: rewriting it re-anchors `starts_at`, which makes
 * the scheduler recompute `next_run_at` and can skip an occurrence about to
 * fire. Switching a loop to a GitHub trigger removes the old schedule, so the
 * workflow does not keep firing on the cadence it no longer shows.
 */
export async function updateLoopHogFlow(
  client: ApiClient,
  projectId: string,
  existing: Pick<Schemas.HogFlow, "id" | "schedules">,
  write: LoopHogFlowWrite,
): Promise<Schemas.HogFlow> {
  // Status is owned by the enable toggle, the origin tag is immutable after
  // create, and the exit condition may have been changed in the workflow
  // editor, so none of them travel with an edit.
  const {
    status: _status,
    origin_product: _origin,
    exit_condition: _exit,
    ...content
  } = write.flow;
  const flow = await patchHogFlow(client, projectId, existing.id, content);
  try {
    return await reconcileSchedule(client, projectId, existing, flow, write);
  } catch (error) {
    throw new LoopScheduleSaveError(error);
  }
}

async function reconcileSchedule(
  client: ApiClient,
  projectId: string,
  existing: Pick<Schemas.HogFlow, "id" | "schedules">,
  flow: Schemas.HogFlow,
  write: LoopHogFlowWrite,
): Promise<Schemas.HogFlow> {
  const current = existing.schedules?.[0];
  if (!write.schedule) {
    for (const schedule of existing.schedules ?? []) {
      await deleteHogFlowSchedule(client, projectId, existing.id, schedule.id);
    }
    return { ...flow, schedules: [] };
  }
  if (current && hogFlowScheduleMatches(current, write.schedule)) {
    return flow;
  }
  const schedule = current
    ? await updateHogFlowSchedule(
        client,
        projectId,
        existing.id,
        current.id,
        write.schedule,
      )
    : await createHogFlowSchedule(
        client,
        projectId,
        existing.id,
        write.schedule,
      );
  return { ...flow, schedules: [schedule] };
}

/** Activation re-runs the workflow's full validation server-side, so a broken
 * flow fails the toggle with a readable error instead of firing broken. */
export async function setLoopHogFlowEnabled(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
  enabled: boolean,
): Promise<Schemas.HogFlow> {
  return patchHogFlow(client, projectId, hogFlowId, {
    status: enabled ? "active" : "draft",
  });
}

/** One key per click: a retry of the same click is deduped server-side, a
 * second click is a second run. */
export async function runLoopHogFlow(
  client: ApiClient,
  projectId: string,
  hogFlowId: string,
): Promise<LoopSchemas.LoopFireRun> {
  await runHogFlow(client, projectId, hogFlowId, crypto.randomUUID());
  // The run endpoint queues an invocation; the task it creates only exists
  // once the workflow step runs, so there is no task id to hand back yet.
  return { created: true, reason: "created", task_id: null, task_run_id: null };
}
