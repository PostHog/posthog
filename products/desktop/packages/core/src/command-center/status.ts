import { getTaskRepository, parseRepository } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";

export type CellStatus = "running" | "waiting" | "idle" | "error" | "completed";

export interface SessionStatusInput {
  status: string;
  cloudStatus?: string;
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
