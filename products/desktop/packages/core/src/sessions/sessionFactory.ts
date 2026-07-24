import type { AgentSession } from "@posthog/shared";

export function createBaseSession(
  taskRunId: string,
  taskId: string,
  taskTitle: string,
): AgentSession {
  return {
    taskRunId,
    taskId,
    taskTitle,
    channel: `agent-event:${taskRunId}`,
    events: [],
    startedAt: Date.now(),
    status: "connecting",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
  };
}
