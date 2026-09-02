export const TASK_DELETION_SERVICE = Symbol.for(
  "posthog.core.tasks.deletionService",
);
export const TASK_DELETION_WORKSPACE_CLIENT = Symbol.for(
  "posthog.core.tasks.deletionWorkspaceClient",
);
export const TASK_DELETION_HOST = Symbol.for("posthog.core.tasks.deletionHost");

export interface TaskWorkspace {
  worktreePath?: string | null;
  folderPath?: string;
}

export interface ITaskDeletionWorkspaceClient {
  getAll(): Promise<Record<string, TaskWorkspace>>;
  delete(input: { taskId: string; mainRepoPath: string }): Promise<unknown>;
}

export interface TaskDeletionFocusSession {
  worktreePath?: string | null;
}

export interface TaskDeletionView {
  type: string;
  data?: { id?: string } | null;
}

export interface ITaskDeletionHost {
  getSession(): TaskDeletionFocusSession | null;
  disableFocus(): Promise<unknown>;
  confirmDeleteTask(input: {
    taskTitle: string;
    hasWorktree: boolean;
  }): Promise<{ confirmed: boolean }>;
  unpin(taskId: string): Promise<void>;
  getCurrentView(): TaskDeletionView | undefined;
  navigateToTaskInput(): void;
}
