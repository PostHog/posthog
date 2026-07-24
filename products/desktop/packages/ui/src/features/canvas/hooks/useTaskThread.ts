import {
  TASK_THREAD_SERVICE,
  type TaskThreadService,
} from "@posthog/core/canvas/taskThreadService";
import { useService } from "@posthog/di/react";
import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";

const THREAD_POLL_INTERVAL_MS = 5_000;

export function taskThreadQueryKey(taskId: string | undefined) {
  return ["task-thread", taskId ?? "none"] as const;
}

export function useTaskThread(
  taskId: string | undefined,
  options?: { pollIntervalMs?: number; enabled?: boolean },
): {
  messages: TaskThreadMessage[];
  isLoading: boolean;
} {
  const pollIntervalMs = options?.pollIntervalMs ?? THREAD_POLL_INTERVAL_MS;
  const enabled = options?.enabled ?? true;
  const query = useAuthenticatedQuery<TaskThreadMessage[]>(
    taskThreadQueryKey(taskId),
    (client) => client.getTaskThreadMessages(taskId as string),
    {
      enabled: !!taskId && enabled,
      refetchInterval: pollIntervalMs,
      staleTime: pollIntervalMs,
    },
  );
  return { messages: query.data ?? [], isLoading: query.isLoading };
}

export function usePostTaskThreadMessage(taskId: string | undefined) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (content: string) => {
      if (!client || !taskId) throw new Error("Not authenticated");
      return client.createTaskThreadMessage(taskId, content);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: taskThreadQueryKey(taskId) }),
  });
  return { postMessage: mutation.mutateAsync, isPosting: mutation.isPending };
}

export function usePostTaskThreadMessageToAgent(taskId: string | undefined) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const service = useService<TaskThreadService>(TASK_THREAD_SERVICE);
  const mutation = useMutation({
    mutationFn: async (content: string) => {
      if (!client || !taskId) throw new Error("Not authenticated");
      return service.postMessageToAgent(client, taskId, content);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: taskThreadQueryKey(taskId) }),
  });
  return {
    postMessageToAgent: mutation.mutateAsync,
    isPostingToAgent: mutation.isPending,
  };
}

export function useDeleteTaskThreadMessage(taskId: string | undefined) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (messageId: string) => {
      if (!client || !taskId) throw new Error("Not authenticated");
      return client.deleteTaskThreadMessage(taskId, messageId);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: taskThreadQueryKey(taskId) }),
  });
  return { deleteMessage: mutation.mutateAsync };
}

export function useSendTaskThreadMessageToAgent(taskId: string | undefined) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async (messageId: string) => {
      if (!client || !taskId) throw new Error("Not authenticated");
      return client.sendTaskThreadMessageToAgent(taskId, messageId);
    },
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: taskThreadQueryKey(taskId) }),
  });
  return { sendToAgent: mutation.mutateAsync, isSending: mutation.isPending };
}
