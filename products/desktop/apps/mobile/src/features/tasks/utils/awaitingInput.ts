import type { TaskSession } from "../stores/taskSessionStore";

/**
 * Task ids whose live session is blocked on the user. A run that has reached
 * a terminal status is waiting on nobody, however its log ended.
 */
export function collectAwaitingInputTaskIds(
  sessions: Record<string, TaskSession>,
): Set<string> {
  const taskIds = new Set<string>();
  for (const session of Object.values(sessions)) {
    if (session.isAwaitingUserInput && !session.terminalStatus) {
      taskIds.add(session.taskId);
    }
  }
  return taskIds;
}
