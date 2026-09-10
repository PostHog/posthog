import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { channelFeedQueryRoot } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";
import {
  latestPendingTaskFilings,
  type PendingTaskFiling,
  usePendingTaskFilings,
} from "./usePendingTaskFilings";

// Filing and unfiling both write the task's space, and the request that
// arrives last decides it. One scope for both sends overlapping moves in the
// order the user made them, instead of racing them.
const TASK_CHANNEL_MUTATION_SCOPE = { id: "task-channel" };

export function applyPendingTaskFilings(
  records: ChannelTaskRecord[],
  channelId: string,
  pendingFilings: PendingTaskFiling[],
): ChannelTaskRecord[] {
  const latestByTask = latestPendingTaskFilings(pendingFilings);

  const visible = records.filter((record) => {
    const filing = latestByTask.get(record.taskId);
    return !filing || filing.channelId === channelId;
  });
  const visibleTaskIds = new Set(visible.map((record) => record.taskId));

  for (const filing of latestByTask.values()) {
    if (filing.channelId === channelId && !visibleTaskIds.has(filing.taskId)) {
      visible.push({
        channelId,
        taskId: filing.taskId,
        createdAt: filing.submittedAt,
      });
    }
  }

  return visible;
}

/** Tasks filed to a channel, including pending moves into or out of it. */
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
  const pendingFilings = usePendingTaskFilings();
  const tasks = useMemo(
    () => applyPendingTaskFilings(data ?? [], channelId ?? "", pendingFilings),
    [channelId, data, pendingFilings],
  );

  return { tasks, isLoading };
}

export function useChannelTaskMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  /**
   * Filing moves a task, so at most two channel lists change: the one it lands
   * in and whichever one still shows it. Every other cached channel is
   * untouched, and someone who has browsed a lot of channels holds a lot of
   * those.
   */
  const invalidateChannelLists = (
    taskId: string,
    channelId?: string,
  ): Promise<unknown> => {
    const listsShowingTask = queryClient.invalidateQueries({
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
    if (!channelId) return listsShowingTask;
    return Promise.all([
      listsShowingTask,
      queryClient.invalidateQueries(
        trpc.channelTasks.list.queryFilter({ channelId }),
      ),
    ]);
  };

  const reconcileTaskFiling = (
    taskId: string,
    channelId?: string,
  ): Promise<unknown[]> =>
    Promise.all([
      invalidateChannelLists(taskId, channelId),
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() }),
      queryClient.invalidateQueries({ queryKey: taskKeys.detail(taskId) }),
      queryClient.invalidateQueries({ queryKey: channelFeedQueryRoot }),
    ]);

  const file = useMutation(
    trpc.channelTasks.file.mutationOptions({
      scope: TASK_CHANNEL_MUTATION_SCOPE,
      onSuccess: (_record, variables) =>
        reconcileTaskFiling(variables.taskId, variables.channelId),
      onError: (_error, variables) => {
        void reconcileTaskFiling(variables.taskId, variables.channelId);
      },
    }),
  );
  const unfile = useMutation(
    trpc.channelTasks.unfile.mutationOptions({
      scope: TASK_CHANNEL_MUTATION_SCOPE,
      onSuccess: (_data, variables) => reconcileTaskFiling(variables.taskId),
    }),
  );

  return {
    fileTask: (channelId: string, taskId: string) =>
      file.mutateAsync({ channelId, taskId }),
    unfileTask: (taskId: string) => unfile.mutateAsync({ taskId }),
    isFiling: file.isPending,
    isUnfiling: unfile.isPending,
  };
}
