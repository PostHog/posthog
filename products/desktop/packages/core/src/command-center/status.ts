import { getTaskRepository, parseRepository } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import {
  deriveTaskRunState,
  type SidebarTask,
  type TaskSession,
} from "../sidebar/buildSidebarData";

export type CellStatus = "running" | "waiting" | "idle" | "error" | "completed";

export interface SessionStatusInput {
  status: string;
  cloudStatus?: TaskRunStatus;
  pendingPermissions: { size: number };
  isPromptPending: boolean;
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
