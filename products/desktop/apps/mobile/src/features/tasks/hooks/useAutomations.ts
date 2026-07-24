import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import {
  createTaskAutomation,
  deleteTaskAutomation,
  getTaskAutomation,
  getTaskAutomations,
  runTaskAutomation,
  updateTaskAutomation,
} from "../api";
import type {
  CreateTaskAutomationOptions,
  TaskAutomation,
  UpdateTaskAutomationOptions,
} from "../types";
import { taskKeys } from "./useTasks";

const log = logger.scope("automations-mutations");
const ACTIVE_AUTOMATION_POLLING_INTERVAL_MS = 5_000;

export const automationKeys = {
  all: ["task-automations"] as const,
  lists: () => [...automationKeys.all, "list"] as const,
  list: () => [...automationKeys.lists(), "all"] as const,
  details: () => [...automationKeys.all, "detail"] as const,
  detail: (id: string) => [...automationKeys.details(), id] as const,
};

export function getAutomationPollingInterval(
  automationData: TaskAutomation | TaskAutomation[] | undefined,
): number | false {
  if (!automationData) {
    return false;
  }

  if (Array.isArray(automationData)) {
    return automationData.some(
      (automation) => automation.last_run_status === "running",
    )
      ? ACTIVE_AUTOMATION_POLLING_INTERVAL_MS
      : false;
  }

  return automationData.last_run_status === "running"
    ? ACTIVE_AUTOMATION_POLLING_INTERVAL_MS
    : false;
}

function invalidateAutomationAndTaskLists(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  queryClient.invalidateQueries({ queryKey: automationKeys.lists() });
  queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
}

export function useAutomations() {
  const { projectId, oauthAccessToken } = useAuthStore();

  const query = useQuery({
    queryKey: automationKeys.list(),
    queryFn: getTaskAutomations,
    enabled: !!projectId && !!oauthAccessToken,
    refetchInterval: (query) =>
      getAutomationPollingInterval(
        query.state.data as TaskAutomation[] | undefined,
      ),
  });

  return {
    automations: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    refetch: query.refetch,
  };
}

export function useAutomation(automationId: string) {
  const { projectId, oauthAccessToken } = useAuthStore();

  return useQuery({
    queryKey: automationKeys.detail(automationId),
    queryFn: () => getTaskAutomation(automationId),
    enabled: !!projectId && !!oauthAccessToken && !!automationId,
    refetchInterval: (query) =>
      getAutomationPollingInterval(
        query.state.data as TaskAutomation | undefined,
      ),
  });
}

export function useCreateTaskAutomation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (options: CreateTaskAutomationOptions) =>
      createTaskAutomation(options),
    onSuccess: (automation) => {
      queryClient.setQueryData(
        automationKeys.detail(automation.id),
        automation,
      );
      invalidateAutomationAndTaskLists(queryClient);
    },
    onError: (error) => {
      log.error("Failed to create automation", error.message);
    },
  });
}

export function useUpdateTaskAutomation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      automationId,
      updates,
    }: {
      automationId: string;
      updates: UpdateTaskAutomationOptions;
    }) => updateTaskAutomation(automationId, updates),
    onSuccess: (automation, { automationId }) => {
      queryClient.setQueryData<TaskAutomation>(
        automationKeys.detail(automationId),
        automation,
      );
      invalidateAutomationAndTaskLists(queryClient);
    },
    onError: (error) => {
      log.error("Failed to update automation", error.message);
    },
  });
}

export function useDeleteTaskAutomation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (automationId: string) => deleteTaskAutomation(automationId),
    onSuccess: (_, automationId) => {
      queryClient.removeQueries({
        queryKey: automationKeys.detail(automationId),
      });
      invalidateAutomationAndTaskLists(queryClient);
    },
    onError: (error) => {
      log.error("Failed to delete automation", error.message);
    },
  });
}

export function useRunTaskAutomation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (automationId: string) => runTaskAutomation(automationId),
    onSuccess: (automation, automationId) => {
      queryClient.setQueryData<TaskAutomation>(
        automationKeys.detail(automationId),
        automation,
      );
      invalidateAutomationAndTaskLists(queryClient);
    },
    onError: (error) => {
      log.error("Failed to run automation", error.message);
    },
  });
}
