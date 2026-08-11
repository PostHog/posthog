import { filterAndSortTasks } from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStore, useUserQuery } from "@/features/auth";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { useTaskStore } from "../stores/taskStore";
import type { CreateTaskOptions } from "../types";

const log = logger.scope("tasks-mutations");
const ACTIVE_TASK_POLLING_INTERVAL_MS = 5_000;
const TERMINAL_TASK_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export const taskKeys = {
  all: ["tasks"] as const,
  lists: () => [...taskKeys.all, "list"] as const,
  list: (filters?: {
    repository?: string;
    createdBy?: number;
    originProduct?: string;
  }) => [...taskKeys.lists(), filters] as const,
  details: () => [...taskKeys.all, "detail"] as const,
  detail: (id: string) => [...taskKeys.details(), id] as const,
};

export function getTaskPollingInterval(
  taskData: Task | Task[] | undefined,
): number | false {
  if (!taskData) {
    return false;
  }

  if (Array.isArray(taskData)) {
    return taskData.some((task) => {
      const status = task.latest_run?.status;
      return !!status && !TERMINAL_TASK_RUN_STATUSES.has(status);
    })
      ? ACTIVE_TASK_POLLING_INTERVAL_MS
      : false;
  }

  const status = taskData.latest_run?.status;
  return status && !TERMINAL_TASK_RUN_STATUSES.has(status)
    ? ACTIVE_TASK_POLLING_INTERVAL_MS
    : false;
}

/**
 * Tasks shown in mobile lists. Desktop-local runs are listed too — they are
 * marked in the row and offer "Continue in cloud" on the detail screen, so
 * hiding them would just lose work the user started on their laptop.
 * Automation tasks are hidden unless a caller asks for them — they have their
 * own tab and would show up twice in the main list. Everything else mirrors
 * desktop, which applies no origin filter at all.
 */
export function filterListedTasks(
  tasks: readonly Task[],
  includeAutomation = false,
): Task[] {
  return tasks.filter(
    (task) => includeAutomation || task.origin_product !== "automation",
  );
}

export function useTasks(filters?: {
  repository?: string;
  originProduct?: string;
}) {
  const { projectId, oauthAccessToken } = useAuthStore();
  const { data: currentUser } = useUserQuery();
  const { sortMode, showInternal, filter } = useTaskStore();

  const queryFilters = {
    ...filters,
    createdBy: currentUser?.id,
  };

  // An explicit origin filter means the caller (e.g. the automations tab)
  // wants exactly what the server returned.
  const includeAutomation = filters?.originProduct !== undefined;

  const query = useQuery({
    queryKey: taskKeys.list(queryFilters),
    queryFn: () => getPostHogApiClient().getTasks(queryFilters),
    enabled: !!projectId && !!oauthAccessToken && !!currentUser?.id,
    // Poll on what the list actually shows — a hidden automation task with an
    // active run must not pin the 5s interval.
    refetchInterval: (query) =>
      getTaskPollingInterval(
        filterListedTasks(
          (query.state.data as Task[] | undefined) ?? [],
          includeAutomation,
        ),
      ),
  });

  // Memoized because callers use these arrays as effect/memo dependencies — a
  // fresh array every render would defeat the task list's grouping memo.
  const listedTasks = useMemo(
    () => filterListedTasks(query.data ?? [], includeAutomation),
    [query.data, includeAutomation],
  );

  const filteredTasks = useMemo(
    () => filterAndSortTasks(listedTasks, sortMode, showInternal, filter),
    [listedTasks, sortMode, showInternal, filter],
  );

  return {
    tasks: filteredTasks,
    allTasks: listedTasks,
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
}

export function useTask(taskId: string) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery({
    queryKey: taskKeys.detail(taskId),
    queryFn: () => getPostHogApiClient().getTask(taskId),
    enabled: !!projectId && !!oauthAccessToken && !!taskId,
    refetchInterval: (query) =>
      getTaskPollingInterval(query.state.data as Task | undefined),
  });
}

export function useCreateTask() {
  const queryClient = useQueryClient();

  const invalidateTasks = () => {
    queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
  };

  const mutation = useMutation({
    mutationFn: (options: CreateTaskOptions) =>
      getPostHogApiClient().createTask(options),
    onSuccess: () => {
      invalidateTasks();
    },
    onError: (error) => {
      log.error("Failed to create task", error.message);
    },
  });

  return { ...mutation, invalidateTasks };
}

export function useUpdateTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      taskId,
      updates,
    }: {
      taskId: string;
      updates: Partial<Task>;
    }) => {
      const client = getPostHogApiClient();
      return client.updateTask(
        taskId,
        updates as Parameters<typeof client.updateTask>[1],
      );
    },
    onSuccess: (updatedTask, { taskId }) => {
      // Update the detail cache immediately
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
    onError: (error) => {
      log.error("Failed to update task", error.message);
    },
  });
}

export function useDeleteTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) => getPostHogApiClient().deleteTask(taskId),
    onSuccess: (_, taskId) => {
      // Remove from detail cache
      queryClient.removeQueries({ queryKey: taskKeys.detail(taskId) });
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
    onError: (error) => {
      log.error("Failed to delete task", error.message);
    },
  });
}

export function useRunTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (taskId: string) =>
      getPostHogApiClient().runTaskInCloud(taskId),
    onSuccess: (updatedTask, taskId) => {
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
    onError: (error) => {
      log.error("Failed to run task", error.message);
    },
  });
}
