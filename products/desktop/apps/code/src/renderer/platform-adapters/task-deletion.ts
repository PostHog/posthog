import type {
  ITaskDeletionHost,
  ITaskDeletionWorkspaceClient,
  TaskDeletionFocusSession,
  TaskDeletionView,
  TaskWorkspace,
} from "@posthog/core/tasks/identifiers";
import { useFocusStore } from "@posthog/ui/features/focus/focusStore";
import { pinnedTasksApi } from "@posthog/ui/features/sidebar/taskMetaApi";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { trpcClient } from "@renderer/trpc/client";

export const taskDeletionWorkspaceClient: ITaskDeletionWorkspaceClient = {
  getAll() {
    return trpcClient.workspace.getAll.query() as Promise<
      Record<string, TaskWorkspace>
    >;
  },
  delete(input) {
    return trpcClient.workspace.delete.mutate(input);
  },
};

export const taskDeletionHost: ITaskDeletionHost = {
  getSession(): TaskDeletionFocusSession | null {
    return useFocusStore.getState().session;
  },
  disableFocus() {
    return useFocusStore.getState().disableFocus();
  },
  confirmDeleteTask(input) {
    return trpcClient.contextMenu.confirmDeleteTask.mutate(input);
  },
  unpin(taskId) {
    return pinnedTasksApi.unpin(taskId);
  },
  getCurrentView(): TaskDeletionView | undefined {
    const view = getAppViewSnapshot();
    return {
      type: view.type,
      data: view.taskId ? { id: view.taskId } : null,
    } as TaskDeletionView;
  },
  navigateToTaskInput() {
    openTaskInput();
  },
};
