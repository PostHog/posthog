import type { ArchivedTask } from "@posthog/shared";

export interface OptimisticWorkspaceInfo {
  folderId?: string;
  mode?: ArchivedTask["mode"];
  worktreeName?: string | null;
  branchName?: string | null;
}

export function buildOptimisticArchivedTask(
  taskId: string,
  workspace: OptimisticWorkspaceInfo | null,
  archivedAt: string = new Date().toISOString(),
): ArchivedTask {
  return {
    taskId,
    archivedAt,
    folderId: workspace?.folderId ?? "",
    mode: workspace?.mode ?? "worktree",
    worktreeName: workspace?.worktreeName ?? null,
    branchName: workspace?.branchName ?? null,
    checkpointId: null,
  };
}

export function appendArchivedTaskId(
  old: string[] | undefined,
  taskId: string,
): string[] {
  return old ? [...old, taskId] : [taskId];
}

export function removeArchivedTaskId(
  old: string[] | undefined,
  taskId: string,
): string[] {
  return old ? old.filter((id) => id !== taskId) : [];
}

export function appendOptimisticArchivedTask(
  old: ArchivedTask[] | undefined,
  optimistic: ArchivedTask,
): ArchivedTask[] {
  return old ? [...old, optimistic] : [optimistic];
}

export function removeArchivedTask(
  old: ArchivedTask[] | undefined,
  taskId: string,
): ArchivedTask[] {
  return old ? old.filter((a) => a.taskId !== taskId) : [];
}
