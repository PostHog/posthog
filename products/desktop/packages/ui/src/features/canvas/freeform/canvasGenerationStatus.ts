import type { AgentSession } from "@posthog/shared";
import {
  isTerminalStatus,
  type TaskRun,
  type TaskRunStatus,
} from "@posthog/shared/domain-types";

export interface CanvasGenerationStatusInput {
  /** The canvas's in-flight generation task id, or null if none. */
  genTaskId: string | null;
  /** True while the task record is still loading for the first time. */
  genTaskLoading: boolean;
  /** The task's latest run record (carries environment + persisted status). */
  latestRun: Pick<TaskRun, "environment" | "status"> | undefined;
  /** The live ACP session for the task, if one is connected in this client. */
  session:
    | Pick<AgentSession, "status" | "cloudStatus" | "isPromptPending">
    | undefined;
}

export type CanvasTerminalStatus = Extract<
  TaskRunStatus,
  "completed" | "failed" | "cancelled"
>;

// Whether a canvas generation task is still actively running.
//
// Cloud and local report progress through different channels:
//   - cloud: status comes from the live session's `cloudStatus`, falling back to
//     the persisted run record — running until that status is terminal.
//   - local: progress is tied to the live ACP session (connecting/connected).
//     But the session can go stale or stall without cleanly disconnecting, so a
//     terminal run record (completed/failed/cancelled) ALWAYS wins — otherwise a
//     hung session pins the canvas in the "Generating" state indefinitely.
export function isCanvasGenerationRunning({
  genTaskId,
  genTaskLoading,
  latestRun,
  session,
}: CanvasGenerationStatusInput): boolean {
  if (!genTaskId) return false;
  // Assume running while the task record is still loading.
  if (genTaskLoading) return true;

  if (latestRun?.environment === "cloud") {
    const cloudStatus = session?.cloudStatus ?? latestRun.status;
    return !isTerminalStatus(cloudStatus);
  }

  // Local: a terminal run record means the run is done regardless of a stale or
  // stuck live session, so it can never strand the canvas on "Generating".
  if (isTerminalStatus(latestRun?.status)) return false;
  return session?.status === "connecting" || session?.status === "connected";
}

// Whether the agent is ACTIVELY producing the canvas right now. This is the
// signal that drives the "Generating…" UI and the completion toast, and it's
// finer-grained than isCanvasGenerationRunning: a local ACP session lingers
// "connected" after its single generation prompt finishes, so here a local run
// keys off the pending prompt rather than the connection — the signal clears the
// moment generation actually ends, not whenever the session disconnects.
export function isCanvasGenerating({
  genTaskId,
  genTaskLoading,
  latestRun,
  session,
}: CanvasGenerationStatusInput): boolean {
  if (!genTaskId) return false;
  if (genTaskLoading) return true;

  if (latestRun?.environment === "cloud") {
    const cloudStatus = session?.cloudStatus ?? latestRun.status ?? null;
    return !isTerminalStatus(cloudStatus);
  }

  if (isTerminalStatus(latestRun?.status)) return false;
  return session?.status === "connecting" || session?.isPromptPending === true;
}

// Whether there's concrete evidence the generation run has actually started, as
// opposed to merely having been created. The completion-toast watcher arms on
// this so the brief gap between creating the task and its live session
// connecting — during which the local "generating" signal momentarily reads
// false — can never be mistaken for a finished run.
export function hasCanvasGenerationStarted({
  latestRun,
  session,
}: {
  latestRun: Pick<TaskRun, "environment" | "status"> | undefined;
  session:
    | Pick<AgentSession, "status" | "cloudStatus" | "isPromptPending">
    | undefined;
}): boolean {
  if (session?.isPromptPending) return true;
  if (session?.status === "connecting" || session?.status === "connected") {
    return true;
  }
  if (latestRun?.status === "in_progress") return true;
  if (latestRun?.environment === "cloud") {
    const status = session?.cloudStatus ?? latestRun?.status;
    return status === "in_progress" || status === "queued";
  }
  return false;
}

// The terminal status to report once generation has finished. Cloud runs carry
// it on the live session's cloudStatus (falling back to the persisted run);
// local runs read the persisted run record. Anything that isn't an explicit
// failure/cancellation is treated as a successful completion — a local run whose
// record hasn't flipped terminal yet still finished by producing its canvas.
export function resolveCanvasGenerationStatus({
  latestRun,
  session,
}: {
  latestRun: Pick<TaskRun, "environment" | "status"> | undefined;
  session: Pick<AgentSession, "cloudStatus"> | undefined;
}): CanvasTerminalStatus {
  const status =
    latestRun?.environment === "cloud"
      ? (session?.cloudStatus ?? latestRun?.status)
      : latestRun?.status;
  if (status === "failed" || status === "cancelled") return status;
  return "completed";
}
