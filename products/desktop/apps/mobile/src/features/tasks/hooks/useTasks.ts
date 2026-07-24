import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore, useUserQuery } from "@/features/auth";
import { logger } from "@/lib/logger";
import {
  createTask,
  deleteTask,
  getTask,
  getTasks,
  runTaskInCloud,
  updateTask,
} from "../api";
import { filterAndSortTasks, useTaskStore } from "../stores/taskStore";
import type { CreateTaskOptions, Task } from "../types";

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
    queryFn: () => getTasks(queryFilters),
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
    queryFn: () => getTask(taskId),
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
    mutationFn: (options: CreateTaskOptions) => createTask(options),
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
    }) => updateTask(taskId, updates),
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
    mutationFn: (taskId: string) => deleteTask(taskId),
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
    mutationFn: (taskId: string) => runTaskInCloud(taskId),
    onSuccess: (updatedTask, taskId) => {
      queryClient.setQueryData(taskKeys.detail(taskId), updatedTask);
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
    },
    onError: (error) => {
      log.error("Failed to run task", error.message);
    },
  });
}
