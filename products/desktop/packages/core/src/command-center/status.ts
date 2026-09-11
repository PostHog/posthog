import {
  type AcpMessage,
  getTaskRepository,
  parseRepository,
} from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { createAppendOnlyTracker } from "../sessions/appendOnlyTracker";
import {
  deriveTaskRunState,
  isTaskUnread,
  type SidebarTask,
  type TaskSession,
  type TaskTimestamp,
} from "../sidebar/buildSidebarData";

export type CellStatus = "running" | "waiting" | "idle" | "error" | "completed";

export interface SessionStatusInput {
  status: string;
  cloudStatus?: TaskRunStatus;
  pendingPermissions: { size: number };
  isPromptPending: boolean;
  events?: readonly AcpMessage[];
  lastStopReason?: string;
}

function readStopReason(event: AcpMessage): string | undefined {
  const message = event.message;
  if (!("result" in message)) return undefined;
  const result = message.result;
  if (
    typeof result === "object" &&
    result !== null &&
    "stopReason" in result &&
    typeof result.stopReason === "string"
  ) {
    return result.stopReason;
  }
  return undefined;
}

export function latestStopReason(
  events: readonly AcpMessage[],
): string | undefined {
  for (let index = events.length - 1; index >= 0; index--) {
    const stopReason = readStopReason(events[index]);
    if (stopReason !== undefined) return stopReason;
  }
  return undefined;
}

function createStopReasonTracker() {
  return createAppendOnlyTracker<
    { stopReason: string | undefined },
    string | undefined
  >({
    init: () => ({ stopReason: undefined }),
    processEvent: (state, event) => {
      const stopReason = readStopReason(event);
      if (stopReason !== undefined) state.stopReason = stopReason;
    },
    getResult: (state) => state.stopReason,
  });
}

// Weak keys let eviction release a transcript and its derived stop reason together.
const stopReasonTrackers = new WeakMap<
  AcpMessage,
  ReturnType<typeof createStopReasonTracker>
>();

/**
 * Same answer as {@link latestStopReason}, folded incrementally so a streaming
 * transcript costs O(appended) per batch rather than a reverse scan that walks
 * every event back to the previous turn boundary.
 */
export function trackLatestStopReason(
  events: AcpMessage[] | undefined,
): string | undefined {
  const first = events?.[0];
  if (!first || !events) return undefined;
  let tracker = stopReasonTrackers.get(first);
  if (!tracker) {
    tracker = createStopReasonTracker();
    stopReasonTrackers.set(first, tracker);
  }
  return tracker.update(events);
}

export function deriveStatus(
  session: SessionStatusInput | undefined,
): CellStatus {
  if (!session) return "idle";

  if (session.status === "error") return "error";
  if (session.cloudStatus === "failed" || session.cloudStatus === "cancelled")
    return "error";
  if (session.cloudStatus === "completed") return "completed";

  if (session.pendingPermissions.size > 0) return "waiting";

  if (session.status === "connected" && session.isPromptPending)
    return "running";

  if (
    (session.lastStopReason ?? latestStopReason(session.events ?? [])) ===
    "cancelled"
  )
    return "error";

  return "idle";
}

export function deriveTaskCellStatus(
  task: Pick<SidebarTask, "id" | "latest_run">,
  session: (TaskSession & SessionStatusInput) | undefined,
): CellStatus {
  const runState = deriveTaskRunState(task, session);
  switch (runState.taskRunStatus) {
    case "completed":
      return "completed";
    case "failed":
    case "cancelled":
      return "error";
  }

  const sessionRunsLatestRun = session?.taskRunId === runState.taskRunId;
  if (
    sessionRunsLatestRun &&
    session &&
    (session.status === "error" ||
      session.cloudStatus === "failed" ||
      session.cloudStatus === "cancelled")
  ) {
    return "error";
  }
  if (runState.needsPermission) return "waiting";
  if (runState.isGenerating) return "running";
  return sessionRunsLatestRun ? deriveStatus(session) : "idle";
}

export function hasUnseenCompletion(
  status: CellStatus,
  activityAt: string,
  timestamp: TaskTimestamp | undefined,
): boolean {
  if (status !== "idle" && status !== "completed") return false;
  return isTaskUnread(activityAt, timestamp);
}

export function getRepoName(task: Task): string | null {
  const repository = getTaskRepository(task);
  if (!repository) return null;
  const parsed = parseRepository(repository);
  return parsed?.repoName ?? repository;
}

export interface StatusSummary {
  total: number;
  running: number;
  waiting: number;
  idle: number;
  error: number;
  completed: number;
}

export function buildStatusSummary(
  cells: { taskId: string | null; task?: unknown; status: CellStatus }[],
): StatusSummary {
  const populated = cells.filter((c) => c.taskId && c.task);
  return {
    total: populated.length,
    running: populated.filter((c) => c.status === "running").length,
    waiting: populated.filter((c) => c.status === "waiting").length,
    idle: populated.filter((c) => c.status === "idle").length,
    error: populated.filter((c) => c.status === "error").length,
    completed: populated.filter((c) => c.status === "completed").length,
  };
}
