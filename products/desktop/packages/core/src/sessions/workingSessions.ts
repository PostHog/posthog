import type { AgentSession } from "@posthog/shared";

export interface WorkingLocalSession {
  taskId: string;
  taskRunId: string;
  taskTitle: string;
}

export type WorkingSessionFields = Pick<
  AgentSession,
  | "taskId"
  | "taskRunId"
  | "taskTitle"
  | "isPromptPending"
  | "isCompacting"
  | "pendingPermissions"
  | "messageQueue"
  | "isCloud"
  | "startedAt"
>;

/**
 * The same busy states `isSessionIdle` names in sessionEviction. A queued
 * message lives only in memory, and the turn-end drain runs a tick after
 * `isPromptPending` clears, so watching that flag alone lets a restart land in
 * the gap and quit with the user's queued prompts still unsent.
 */
function hasWorkInFlight(session: WorkingSessionFields): boolean {
  return (
    session.isPromptPending ||
    session.isCompacting ||
    session.pendingPermissions.size > 0 ||
    session.messageQueue.length > 0
  );
}

/**
 * Local sessions with agent work in flight — the work a host restart would
 * kill. Cloud runs keep executing server-side through a restart, so they are
 * excluded.
 */
export function listWorkingLocalSessions(
  sessions: Record<string, WorkingSessionFields>,
): WorkingLocalSession[] {
  return Object.values(sessions)
    .filter((session) => hasWorkInFlight(session) && !session.isCloud)
    .sort((a, b) => a.startedAt - b.startedAt)
    .map((session) => ({
      taskId: session.taskId,
      taskRunId: session.taskRunId,
      taskTitle: session.taskTitle.trim() || "Untitled task",
    }));
}

/**
 * Equality signature for store subscriptions: changes only when membership or
 * a title changes, not on every streamed event.
 */
export function computeWorkingLocalSessionsSignature(
  sessions: Record<string, WorkingSessionFields>,
): string {
  return listWorkingLocalSessions(sessions)
    .map((session) => `${session.taskRunId}:${session.taskTitle}`)
    .join(";");
}
