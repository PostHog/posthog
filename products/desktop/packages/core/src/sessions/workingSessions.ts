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
  | "isCloud"
  | "startedAt"
>;

/**
 * Local sessions with an agent turn in flight — the work a host restart would
 * kill. Cloud runs keep executing server-side through a restart, so they are
 * excluded.
 */
export function listWorkingLocalSessions(
  sessions: Record<string, WorkingSessionFields>,
): WorkingLocalSession[] {
  return Object.values(sessions)
    .filter((session) => session.isPromptPending && !session.isCloud)
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
