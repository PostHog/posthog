import type {
  ITaskDeletionHost,
  ITaskDeletionWorkspaceClient,
  TaskDeletionFocusSession,
  TaskDeletionView,
} from "@posthog/core/tasks/identifiers";
import { pinnedTasksApi } from "@posthog/ui/features/sidebar/taskMetaApi";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";

// Task deletion on web: the actual task delete goes through the PostHog API
// (client.deleteTask, passed into TaskDeletionService). These clients only
// cover local-worktree cleanup + host UI. On the cloud-only host there are no
// local worktrees, so the workspace client is inert (getAll -> {} means the
// service never takes the local-cleanup branch).
export const webTaskDeletionWorkspaceClient: ITaskDeletionWorkspaceClient = {
  getAll: () => Promise.resolve({}),
  delete: () => Promise.resolve(undefined),
};

export const webTaskDeletionHost: ITaskDeletionHost = {
  // No local focus/worktree on web.
  getSession: (): TaskDeletionFocusSession | null => null,
  disableFocus: () => Promise.resolve(undefined),
  // Desktop shows a native confirm dialog; the browser has its own.
  confirmDeleteTask: (input) =>
    Promise.resolve({
      confirmed: window.confirm(`Delete "${input.taskTitle}"?`),
    }),
  unpin: (taskId) => pinnedTasksApi.unpin(taskId),
  getCurrentView: (): TaskDeletionView | undefined => {
    const view = getAppViewSnapshot();
    return {
      type: view.type,
      data: view.taskId ? { id: view.taskId } : null,
    };
  },
  navigateToTaskInput: () => openTaskInput(),
};
