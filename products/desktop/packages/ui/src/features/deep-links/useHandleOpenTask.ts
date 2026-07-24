import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useTaskChannelMap } from "@posthog/ui/features/canvas/hooks/useTaskChannelMap";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { toast } from "@posthog/ui/primitives/toast";
import { openTask as openTaskHelper } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

const log = logger.scope("open-task");

/**
 * Opens a task from a deep link / notification click, provisioning its
 * workspace via the TASK_SERVICE saga (so it works even when the task isn't
 * loaded yet). Returns a stable callback shared by the task URL-scheme deep link
 * (`useTaskDeepLink`) and the generic notification-target consumer
 * (`useOpenTargetDeepLink`).
 */
export function useHandleOpenTask(): (
  taskId: string,
  taskRunId?: string,
) => Promise<void> {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const { markAsViewed } = useTaskViewed();
  const queryClient = useQueryClient();

  // A task filed to a Project Bluebird channel opens in the channel-organized
  // view under /website. Gate the channel fetches behind the flag.
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const { channels } = useChannels({ enabled: bluebirdEnabled });
  const channelMap = useTaskChannelMap(channels, { enabled: bluebirdEnabled });
  // Mirror the latest map into a ref so the stable callback can read it without
  // listing the map in its deps — otherwise it'd be recreated on every poll.
  const channelMapRef = useRef(channelMap);
  useEffect(() => {
    channelMapRef.current = channelMap;
  }, [channelMap]);

  return useCallback(
    async (taskId: string, taskRunId?: string) => {
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
        const channel = bluebirdEnabled
          ? channelMapRef.current.get(task.id)
          : undefined;
        void openTaskHelper(
          task,
          channel ? { channelId: channel.id } : undefined,
        );
        log.info(`Opened task from deep link: ${taskId}`);
      } catch (error) {
        log.error("Unexpected error opening task from deep link:", error);
        toast.error("Failed to open task");
      }
    },
    [markAsViewed, queryClient, taskService, bluebirdEnabled],
  );
}
