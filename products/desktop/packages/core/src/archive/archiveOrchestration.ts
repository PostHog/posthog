import type { ArchivedTask } from "@posthog/shared";
import {
  appendArchivedTaskId,
  appendOptimisticArchivedTask,
  buildOptimisticArchivedTask,
  type OptimisticWorkspaceInfo,
  removeArchivedTask,
  removeArchivedTaskId,
} from "./optimisticArchive";

export interface ArchiveWorkspaceInfo extends OptimisticWorkspaceInfo {
  worktreePath?: string | null;
}

export interface ArchiveCacheWriter {
  cancelPathFilter(): Promise<void>;
  invalidatePathFilter(): void;
  setArchivedTaskIds(updater: (old: string[] | undefined) => string[]): void;
  setArchiveList(
    updater: (old: ArchivedTask[] | undefined) => ArchivedTask[],
  ): void;
}

export interface ArchiveOrchestrationDeps {
  getWorkspace(taskId: string): Promise<ArchiveWorkspaceInfo | null>;
  getPinnedTaskIds(): Promise<string[]>;
  unpin(taskId: string): Promise<void>;
  togglePin(taskId: string): Promise<void>;
  navigateAwayFromTaskIfActive(taskId: string): void;
  clearTerminalStates(taskId: string): void;
  snapshotCommandCenter(taskId: string): { index: number; wasActive: boolean };
  removeFromCommandCenter(taskId: string): void;
  restoreCommandCenter(
    taskId: string,
    snapshot: { index: number; wasActive: boolean },
  ): void;
  getFocusedWorktreePath(): string | null | undefined;
  disableFocus(): Promise<void>;
  stopCloudRun(taskId: string, runId?: string): Promise<boolean>;
  disconnectFromTask(taskId: string): Promise<void>;
  archive(taskId: string): Promise<void>;
  clearViewedState(taskId: string): void;
  logError(message: string, error: unknown): void;
  cache: ArchiveCacheWriter;
}

export interface ArchiveTaskOptions {
  skipNavigate?: boolean;
  /**
   * When true (default), the task is removed from the sidebar list immediately
   * via an optimistic cache write and rolled back on failure. When false, the
   * row stays put until the archive actually succeeds — used by the interactive
   * single-archive flow so the row can show a spinner until it's confirmed gone.
   */
  optimistic?: boolean;
}

export async function archiveTask(
  taskId: string,
  deps: ArchiveOrchestrationDeps,
  options?: ArchiveTaskOptions,
): Promise<void> {
  const workspace = await deps.getWorkspace(taskId);
  const stopped = await deps.stopCloudRun(taskId);
  if (!stopped) {
    throw new Error("Couldn't stop the task. Try again in a moment.");
  }

  const optimistic = options?.optimistic ?? true;
  const pinnedTaskIds = await deps.getPinnedTaskIds();
  const wasPinned = pinnedTaskIds.includes(taskId);

  if (!options?.skipNavigate) {
    deps.navigateAwayFromTaskIfActive(taskId);
  }

  const commandCenterSnapshot = deps.snapshotCommandCenter(taskId);

  await deps.unpin(taskId);
  deps.removeFromCommandCenter(taskId);

  await deps.cache.cancelPathFilter();

  const optimisticArchived = buildOptimisticArchivedTask(taskId, workspace);

  const applyArchivedCacheWrites = () => {
    deps.cache.setArchivedTaskIds((old) => appendArchivedTaskId(old, taskId));
    deps.cache.setArchiveList((old) =>
      appendOptimisticArchivedTask(old, optimisticArchived),
    );
  };

  if (optimistic) {
    applyArchivedCacheWrites();
  }

  if (
    workspace?.worktreePath &&
    deps.getFocusedWorktreePath() === workspace.worktreePath
  ) {
    await deps.disableFocus();
  }

  try {
    await deps.disconnectFromTask(taskId);
    await deps.archive(taskId);
    deps.clearTerminalStates(taskId);
    deps.clearViewedState(taskId);
    // Non-optimistic flows keep the row visible during the request, then remove
    // it the moment the archive succeeds.
    if (!optimistic) {
      applyArchivedCacheWrites();
    }
    deps.cache.invalidatePathFilter();
  } catch (error) {
    deps.logError("Failed to archive task", error);

    deps.cache.setArchivedTaskIds((old) => removeArchivedTaskId(old, taskId));
    deps.cache.setArchiveList((old) => removeArchivedTask(old, taskId));
    if (wasPinned) {
      await deps.togglePin(taskId);
    }
    if (commandCenterSnapshot.index !== -1) {
      deps.restoreCommandCenter(taskId, commandCenterSnapshot);
    }

    throw error;
  }
}

export interface ArchiveTasksResult {
  archived: number;
  failed: number;
}

export async function archiveTasks(
  taskIds: string[],
  deps: ArchiveOrchestrationDeps,
): Promise<ArchiveTasksResult> {
  if (taskIds.length === 0) return { archived: 0, failed: 0 };

  let archived = 0;
  let failed = 0;
  for (const id of taskIds) {
    try {
      await archiveTask(id, deps, { skipNavigate: true });
      archived++;
    } catch {
      failed++;
    }
  }
  return { archived, failed };
}

export function shouldNavigateAwayForBulkArchive(
  taskIds: string[],
  activeTaskId: string | null | undefined,
): boolean {
  if (taskIds.length === 0 || !activeTaskId) return false;
  return new Set(taskIds).has(activeTaskId);
}
