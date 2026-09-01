import type { CommentTarget } from "@posthog/core/comments/anchors";
import type { TaskLinkCommentAnchor } from "@posthog/core/links/task-link";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { toast } from "@posthog/ui/primitives/toast";
import { openTask as openTaskHelper } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const log = logger.scope("open-task");

/**
 * Opens a task from a deep link / notification click, provisioning its
 * workspace via the TASK_SERVICE saga (so it works even when the task isn't
 * loaded yet). Returns a stable callback shared by the task URL-scheme deep link
 * (`useTaskDeepLink`) and the generic notification-target consumer
 * (`useOpenTargetDeepLink`).
 */
function commentTargetFromAnchor(
  taskId: string,
  anchor: TaskLinkCommentAnchor,
): CommentTarget {
  if (
    (anchor.scope === "desktop_canvas" || anchor.scope === "task_artifact") &&
    anchor.itemId
  ) {
    return { scope: anchor.scope, itemId: anchor.itemId };
  }
  return { scope: "task", itemId: taskId };
}

export function useHandleOpenTask(): (
  taskId: string,
  taskRunId?: string,
  comment?: TaskLinkCommentAnchor,
) => Promise<void> {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const { markAsViewed } = useTaskViewed();
  const queryClient = useQueryClient();

  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );

  return useCallback(
    async (
      taskId: string,
      taskRunId?: string,
      comment?: TaskLinkCommentAnchor,
    ) => {
      log.info(
        `Opening task from deep link: ${taskId}${taskRunId ? `, run: ${taskRunId}` : ""}`,
      );
      try {
        const result = await taskService.openTask(taskId, taskRunId);
        if (!result.success) {
          log.error("Failed to open task from deep link", {
            taskId,
            taskRunId,
            error: result.error,
            failedStep: result.failedStep,
          });
          toast.error(`Failed to open task: ${result.error}`);
          return;
        }

        const { task } = result.data;
        queryClient.setQueryData<Task[]>(taskKeys.list(), (old) => {
          if (!old) return [task];
          const existingIndex = old.findIndex((t) => t.id === task.id);
          if (existingIndex >= 0) {
            const updated = [...old];
            updated[existingIndex] = task;
            return updated;
          }
          return [task, ...old];
        });
        queryClient.invalidateQueries({ queryKey: taskKeys.lists() });

        markAsViewed(taskId);
        const channelTarget =
          bluebirdEnabled && task.channel
            ? { channelId: task.channel }
            : undefined;
        void openTaskHelper(task, channelTarget);
        if (comment) {
          useCommentNavigationStore
            .getState()
            .requestCommentFocus(
              taskId,
              commentTargetFromAnchor(taskId, comment),
              comment.threadId,
            );
        }
        log.info(`Opened task from deep link: ${taskId}`);
      } catch (error) {
        log.error("Unexpected error opening task from deep link:", error);
        toast.error("Failed to open task");
      }
    },
    [markAsViewed, queryClient, taskService, bluebirdEnabled],
  );
}
