import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { channelFeedQueryRoot } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { spaceTreeTasksQueryRoot } from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import { taskFeedResultsQueryRoot } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { TASK_ACTIVITY_QUERY_KEY } from "@posthog/ui/features/canvas/task-activity/taskActivityQuery";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useChannelTaskMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  /**
   * Filing moves a task, so at most two lists change: the channel it lands in
   * and whichever one still shows it. Every other cached channel is untouched,
   * and someone who has browsed a lot of channels holds a lot of those.
   */
  const invalidateAffected = (taskIds: string[], channelId?: string) => {
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
        return tasks.some((record) => taskIds.includes(record.taskId));
      },
    });
    // Filing rewrites the task's own `channel` field, which these caches carry.
    for (const queryKey of [
      taskKeys.lists(),
      channelFeedQueryRoot,
      spaceTreeTasksQueryRoot,
      taskFeedResultsQueryRoot,
      TASK_ACTIVITY_QUERY_KEY,
      ...taskIds.map((taskId) => taskKeys.detail(taskId)),
    ]) {
      void queryClient.invalidateQueries({ queryKey });
    }
  };

  const file = useMutation(trpc.channelTasks.file.mutationOptions());
  const unfile = useMutation(
    trpc.channelTasks.unfile.mutationOptions({
      onSuccess: (_data, variables) => invalidateAffected([variables.taskId]),
    }),
  );

  return {
    fileTask: async (channelId: string, taskId: string) => {
      await file.mutateAsync({ channelId, taskId });
      invalidateAffected([taskId], channelId);
    },
    // One pass for the whole selection: invalidating per task restarts every
    // feed and tree query N times, and a cancelled refetch still costs its
    // request.
    fileTasks: async (channelId: string, taskIds: string[]) => {
      const results = await Promise.allSettled(
        taskIds.map((taskId) => file.mutateAsync({ channelId, taskId })),
      );
      const filedIds = taskIds.filter(
        (_, i) => results[i].status === "fulfilled",
      );
      const failedIds = taskIds.filter(
        (_, i) => results[i].status === "rejected",
      );
      if (filedIds.length > 0) invalidateAffected(filedIds, channelId);
      return { failedIds };
    },
    // Unfiling clears the task's channel field, so it's keyed on the task id.
    unfileTask: (taskId: string) => unfile.mutateAsync({ taskId }),
    isFiling: file.isPending,
    isUnfiling: unfile.isPending,
  };
}
