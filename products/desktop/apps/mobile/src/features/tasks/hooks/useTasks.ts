import { filterAndSortTasks } from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

  const query = useQuery({
    queryKey: taskKeys.list(queryFilters),
    queryFn: () => getPostHogApiClient().getTasks(queryFilters),
    enabled: !!projectId && !!oauthAccessToken && !!currentUser?.id,
    refetchInterval: (query) =>
      getTaskPollingInterval(query.state.data as Task[] | undefined),
  });

  // Mobile never runs tasks locally — hide desktop-only local runs so the
  // mobile list mirrors what's actually shareable across devices.
  const cloudTasks = (query.data ?? []).filter(
    (task) => task.latest_run?.environment !== "local",
  );

  const filteredTasks = filterAndSortTasks(
    cloudTasks,
    sortMode,
    showInternal,
    filter,
  );

  return {
    tasks: filteredTasks,
    allTasks: cloudTasks,
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

export function useHandoffTask() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ taskId, userId }: { taskId: string; userId: number }) =>
      getPostHogApiClient().handoffTask(taskId, userId),
    // The task may leave the requester's own list, so nothing is seeded.
    onSuccess: (_, { taskId }) => {
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) });
    },
    onError: (error) => {
      log.error("Failed to hand off task", error.message);
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
