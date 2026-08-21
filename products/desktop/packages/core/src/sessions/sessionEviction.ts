import type { AgentSession } from "@posthog/shared";
import { isTerminalStatus } from "@posthog/shared/domain-types";

// Above the Command Center's 3x3 grid so fully-visible layouts never evict.
export const MAX_CONNECTED_SESSIONS = 12;

export function isSessionIdle(session: AgentSession): boolean {
  if (session.status === "connecting") return false;
  if (session.isPromptPending) return false;
  if (session.isCompacting) return false;
  if (session.handoffInProgress) return false;
  if (session.pendingPermissions.size > 0) return false;
  if (session.messageQueue.length > 0) return false;
  if (session.isCloud) return isTerminalStatus(session.cloudStatus);
  return true;
}

export function selectSessionsToEvict(params: {
  sessions: AgentSession[];
  activeTaskId: string;
  protectedTaskIds?: ReadonlySet<string>;
  lastUsedAt: (session: AgentSession) => number;
  maxSessions?: number;
}): AgentSession[] {
  const { sessions, activeTaskId, protectedTaskIds, lastUsedAt } = params;
  const maxSessions = params.maxSessions ?? MAX_CONNECTED_SESSIONS;

  // Reserves a slot for the incoming session even when a resume replaces an
  // existing one; deliberately over-evicts by one in that case.
  const excess = sessions.length - (maxSessions - 1);
  if (excess <= 0) return [];

  return sessions
    .filter(
      (session) =>
        session.taskId !== activeTaskId &&
        !protectedTaskIds?.has(session.taskId) &&
        isSessionIdle(session),
    )
    .sort((a, b) => lastUsedAt(a) - lastUsedAt(b))
    .slice(0, excess);
}
