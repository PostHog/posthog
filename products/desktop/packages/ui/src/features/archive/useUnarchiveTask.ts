import {
  ARCHIVED_TASKS_CONTROLLER,
  type ArchivedTasksController,
  type ContextMenuOutcome,
  type DeleteOutcome,
  type RestoreOutcome,
} from "@posthog/core/archive/archivedTasksController";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { WORKSPACE_QUERY_KEY } from "@posthog/ui/features/workspace/identifiers";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const log = logger.scope("unarchive-task");

export interface UseUnarchiveTask {
  restore(
    taskId: string,
    hasTask: boolean,
    options?: { recreateBranch?: boolean },
  ): Promise<RestoreOutcome>;
  remove(taskId: string): Promise<DeleteOutcome>;
  runContextMenuAction(
    taskId: string,
    taskTitle: string,
    hasTask: boolean,
  ): Promise<ContextMenuOutcome>;
}

export function useUnarchiveTask(): UseUnarchiveTask {
  const controller = useService<ArchivedTasksController>(
    ARCHIVED_TASKS_CONTROLLER,
  );
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();

  // The archive is mirrored onto the task server-side, where it hides the task
  // from every list — so restoring locally has to clear it, or the row comes
  // back on this device and stays gone from the lists the counts are drawn from.
  const clearServerArchived = useCallback(
    async (taskId: string) => {
      if (!client) return;
      try {
        await client.setTaskArchived(taskId, false);
      } catch (error) {
        log.warn(`Failed to unarchive task ${taskId} on the server`, error);
      }
    },
    [client],
  );

  const invalidateTaskListCaches = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY }),
      queryClient.invalidateQueries(trpc.archive.pathFilter()),
      queryClient.refetchQueries({ queryKey: ["tasks"] }),
    ]);
  }, [queryClient, trpc]);

  const restore = useCallback(
    async (
      taskId: string,
      hasTask: boolean,
      options?: { recreateBranch?: boolean },
    ) => {
      const outcome = await controller.restore(taskId, hasTask, options);
      if (outcome.kind === "restored") {
        await clearServerArchived(taskId);
        await invalidateTaskListCaches();
      }
      return outcome;
    },
    [controller, clearServerArchived, invalidateTaskListCaches],
  );

  const remove = useCallback(
    async (taskId: string) => {
      const outcome = await controller.remove(taskId);
      if (outcome.kind === "deleted") {
        await invalidateTaskListCaches();
      }
      return outcome;
    },
    [controller, invalidateTaskListCaches],
  );

  const runContextMenuAction = useCallback(
    async (taskId: string, taskTitle: string, hasTask: boolean) => {
      const outcome = await controller.runContextMenuAction(
        taskId,
        taskTitle,
        hasTask,
      );
      if (outcome.kind === "restore" && outcome.outcome.kind === "restored") {
        await clearServerArchived(taskId);
        await invalidateTaskListCaches();
      } else if (
        outcome.kind === "delete" &&
        outcome.outcome.kind === "deleted"
      ) {
        await invalidateTaskListCaches();
      }
      return outcome;
    },
    [controller, clearServerArchived, invalidateTaskListCaches],
  );

  return { restore, remove, runContextMenuAction };
}
