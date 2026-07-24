import type { Schemas } from "@posthog/api-client";
import {
  type ArchiveCacheWriter,
  type ArchiveOrchestrationDeps,
  type ArchiveTasksResult,
  archiveTask,
  archiveTasks,
  shouldNavigateAwayForBulkArchive,
} from "@posthog/core/archive/archiveOrchestration";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { useHostTRPC } from "@posthog/host-router/react";
import type { Task } from "@posthog/shared/domain-types";
import { useReviewViewedStore } from "@posthog/ui/features/code-review/reviewViewedStore";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { useFocusStore } from "@posthog/ui/features/focus/focusStore";
import { pinnedTasksApi } from "@posthog/ui/features/sidebar/taskMetaApi";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { destroyTaskTerminals } from "@posthog/ui/features/terminal/destroyTaskTerminals";
import { toast } from "@posthog/ui/primitives/toast";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { logger } from "@posthog/ui/shell/logger";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { undoArchive } from "./undoArchive";
import { useUnarchiveTask } from "./useUnarchiveTask";

const log = logger.scope("archive-task");

const UNDO_TOAST_DURATION_MS = 8000;

export interface ArchiveCacheKeys {
  archivedTaskIdsQueryKey: readonly unknown[];
  archiveListQueryKey: readonly unknown[];
  archivePathFilterKey: readonly unknown[];
}

export function useArchiveCacheKeys(): ArchiveCacheKeys {
  const trpc = useHostTRPC();
  return useMemo(
    () => ({
      archivedTaskIdsQueryKey: trpc.archive.archivedTaskIds.queryKey(),
      archiveListQueryKey: trpc.archive.list.queryKey(),
      archivePathFilterKey: trpc.archive.pathFilter().queryKey,
    }),
    [trpc],
  );
}

function makeCacheWriter(
  queryClient: QueryClient,
  keys: ArchiveCacheKeys,
): ArchiveCacheWriter {
  return {
    cancelPathFilter: () =>
      queryClient.cancelQueries({ queryKey: keys.archivePathFilterKey }),
    invalidatePathFilter: () => {
      queryClient.invalidateQueries({ queryKey: keys.archivePathFilterKey });
    },
    setArchivedTaskIds: (updater) =>
      queryClient.setQueryData(keys.archivedTaskIdsQueryKey, updater),
    setArchiveList: (updater) =>
      queryClient.setQueryData(keys.archiveListQueryKey, updater),
  };
}

export function getCachedArchiveTask(
  queryClient: QueryClient,
  taskId: string,
): Pick<Task, "id" | "title" | "created_at" | "repository"> | undefined {
  return (
    queryClient
      .getQueriesData<Task[]>({ queryKey: taskKeys.lists() })
      .flatMap(([, tasks]) => tasks ?? [])
      .find((item) => item.id === taskId) ??
    queryClient
      .getQueriesData<Schemas.TaskSummary[]>({
        queryKey: taskKeys.allSummaries(),
      })
      .flatMap(([, tasks]) => tasks ?? [])
      .find((item) => item.id === taskId)
  );
}

function makeOrchestrationDeps(
  queryClient: QueryClient,
  keys: ArchiveCacheKeys,
  options?: { skipNavigate?: boolean; navigateSpace?: "code" | "website" },
): ArchiveOrchestrationDeps {
  const hostClient = resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
  return {
    async getWorkspace(taskId) {
      const all = await hostClient.workspace.getAll.query();
      return all[taskId] ?? null;
    },
    getPinnedTaskIds: () => pinnedTasksApi.getPinnedTaskIds(),
    unpin: (taskId) => pinnedTasksApi.unpin(taskId),
    togglePin: async (taskId) => {
      await pinnedTasksApi.togglePin(taskId);
    },
    navigateAwayFromTaskIfActive: (taskId) => {
      if (options?.skipNavigate) return;
      const view = getAppViewSnapshot();
      if (view.type === "task-detail" && view.taskId === taskId) {
        openTaskInput(
          options?.navigateSpace ? { space: options.navigateSpace } : undefined,
        );
      }
    },
    clearTerminalStates: (taskId) => destroyTaskTerminals(taskId),
    snapshotCommandCenter: (taskId) => {
      const state = useCommandCenterStore.getState();
      return {
        index: state.cells.indexOf(taskId),
        wasActive: state.activeTaskId === taskId,
      };
    },
    removeFromCommandCenter: (taskId) =>
      useCommandCenterStore.getState().removeTaskById(taskId),
    restoreCommandCenter: (taskId, snapshot) => {
      useCommandCenterStore.setState((s) => {
        const cells = [...s.cells];
        cells[snapshot.index] = taskId;
        return snapshot.wasActive ? { cells, activeTaskId: taskId } : { cells };
      });
    },
    getFocusedWorktreePath: () =>
      useFocusStore.getState().session?.worktreePath,
    disableFocus: async () => {
      log.info("Unfocusing workspace before archiving");
      await useFocusStore.getState().disableFocus();
    },
    stopCloudRun: (taskId, runId) =>
      resolveService<SessionService>(SESSION_SERVICE).stopCloudRun(
        taskId,
        runId,
      ),
    disconnectFromTask: (taskId) =>
      resolveService<SessionService>(SESSION_SERVICE).disconnectFromTask(
        taskId,
      ),
    archive: (taskId) => {
      const task = getCachedArchiveTask(queryClient, taskId);
      return hostClient.archive.archive
        .mutate({
          taskId,
          title: task?.title,
          taskCreatedAt: task?.created_at,
          repository: task?.repository,
        })
        .then(() => undefined);
    },
    clearViewedState: (taskId) =>
      useReviewViewedStore.getState().clearTasks([taskId]),
    logError: (message, error) => log.error(message, error),
    cache: makeCacheWriter(queryClient, keys),
  };
}

export async function archiveTaskImperative(
  taskId: string,
  queryClient: QueryClient,
  keys: ArchiveCacheKeys,
  options?: {
    skipNavigate?: boolean;
    optimistic?: boolean;
    navigateSpace?: "code" | "website";
  },
): Promise<void> {
  await archiveTask(
    taskId,
    makeOrchestrationDeps(queryClient, keys, options),
    options,
  );
}

export async function archiveTasksImperative(
  taskIds: string[],
  queryClient: QueryClient,
  keys: ArchiveCacheKeys,
): Promise<ArchiveTasksResult> {
  const view = getAppViewSnapshot();
  const activeTaskId =
    view.type === "task-detail" ? (view.taskId ?? null) : null;
  if (shouldNavigateAwayForBulkArchive(taskIds, activeTaskId)) {
    openTaskInput();
  }
  return archiveTasks(
    taskIds,
    makeOrchestrationDeps(queryClient, keys, { skipNavigate: true }),
  );
}

export function useArchiveTask(options?: {
  // Which new-task screen to land on if the archived task is the active view.
  // Defaults to Code; the bluebird/channels nav passes "website" so archiving
  // from there returns to the website new-task screen instead.
  navigateSpace?: "code" | "website";
}) {
  const queryClient = useQueryClient();
  const keys = useArchiveCacheKeys();
  const { restore } = useUnarchiveTask();

  const archiveTask = async ({ taskId }: { taskId: string }) => {
    // Non-optimistic: keep the row in place (with a spinner) until the archive
    // is confirmed, rather than removing it instantly and rolling back on error.
    await archiveTaskImperative(taskId, queryClient, keys, {
      optimistic: false,
      navigateSpace: options?.navigateSpace,
    });
    const toastId = `archive-undo-${taskId}`;
    toast.success("Task archived", {
      id: toastId,
      duration: UNDO_TOAST_DURATION_MS,
      action: {
        label: "Undo",
        onClick: () => {
          toast.dismiss(toastId);
          void undoArchive(taskId, restore);
        },
      },
    });
  };

  return { archiveTask };
}
