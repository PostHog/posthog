import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

/** Tasks filed to a channel — the task's `channel` field on the tasks API. */
export function useChannelTasks(channelId: string | undefined): {
  tasks: ChannelTaskRecord[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.channelTasks.list.queryOptions(
      { channelId: channelId ?? "" },
      {
        enabled: !!channelId,
        gcTime: SPACE_QUERY_GC_TIME_MS,
        meta: AUTH_SCOPED_QUERY_META,
        refetchInterval: SPACE_QUERY_REFETCH_INTERVAL_MS,
        staleTime: SPACE_QUERY_STALE_TIME_MS,
      },
    ),
  );
  return { tasks: data ?? [], isLoading };
}

/**
 * Warm the filed-tasks cache for a channel ahead of opening it (e.g. on hover),
 * so expanding the channel doesn't cold-fetch its tasks. Respects the same
 * staleTime, so it no-ops when the data is already fresh.
 */
export function usePrefetchChannelTasks(): (channelId: string) => void {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useCallback(
    (channelId: string) => {
      void queryClient.prefetchQuery(
        trpc.channelTasks.list.queryOptions(
          { channelId },
          {
            gcTime: SPACE_QUERY_GC_TIME_MS,
            meta: AUTH_SCOPED_QUERY_META,
            staleTime: SPACE_QUERY_STALE_TIME_MS,
          },
        ),
      );
    },
    [trpc, queryClient],
  );
}

export function useChannelTaskMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  /**
   * Filing moves a task, so at most two lists change: the channel it lands in
   * and whichever one still shows it. Every other cached channel is untouched,
   * and someone who has browsed a lot of channels holds a lot of those.
   */
  const invalidateAffected = (taskId: string, channelId?: string) => {
    if (channelId) {
      void queryClient.invalidateQueries(
        trpc.channelTasks.list.queryFilter({ channelId }),
      );
    }
    void queryClient.invalidateQueries({
      ...trpc.channelTasks.list.pathFilter(),
      predicate: (query) => {
        const tasks = query.state.data as ChannelTaskRecord[] | undefined;
        // A list still loading has no membership to check, and its in-flight
        // request may have been sent before this mutation. Refetch rather than
        // let a pre-mutation response land and sit fresh.
        if (!tasks) return true;
        return tasks.some((record) => record.taskId === taskId);
      },
    });
  };

  const file = useMutation(
    trpc.channelTasks.file.mutationOptions({
      onSuccess: (_data, variables) =>
        invalidateAffected(variables.taskId, variables.channelId),
    }),
  );
  const unfile = useMutation(
    trpc.channelTasks.unfile.mutationOptions({
      onSuccess: (_data, variables) => invalidateAffected(variables.taskId),
    }),
  );

  return {
    fileTask: (channelId: string, taskId: string) =>
      file.mutateAsync({ channelId, taskId }),
    // Unfiling clears the task's channel field, so it's keyed on the task id.
    unfileTask: (taskId: string) => unfile.mutateAsync({ taskId }),
    isFiling: file.isPending,
    isUnfiling: unfile.isPending,
  };
}
