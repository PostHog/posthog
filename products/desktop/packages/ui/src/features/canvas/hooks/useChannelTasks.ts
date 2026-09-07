import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import type { Task } from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  channelFeedQueryKey,
  channelFeedQueryRoot,
} from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

const latestFilings = new WeakMap<QueryClient, Map<string, symbol>>();

function latestFilingsFor(queryClient: QueryClient): Map<string, symbol> {
  const existing = latestFilings.get(queryClient);
  if (existing) return existing;
  const filings = new Map<string, symbol>();
  latestFilings.set(queryClient, filings);
  return filings;
}

function restoreChannelTaskRecord(
  current: ChannelTaskRecord[] | undefined,
  previous: ChannelTaskRecord[] | undefined,
  taskId: string,
): ChannelTaskRecord[] | undefined {
  const previousRecord = previous?.find((record) => record.taskId === taskId);
  const withoutTask = current?.filter((record) => record.taskId !== taskId);
  if (!previousRecord) return withoutTask;
  if (!withoutTask) return previous;

  const previousIndex = previous?.findIndex(
    (record) => record.taskId === taskId,
  );
  const insertAt = Math.min(
    previousIndex ?? withoutTask.length,
    withoutTask.length,
  );
  return [
    ...withoutTask.slice(0, insertAt),
    previousRecord,
    ...withoutTask.slice(insertAt),
  ];
}

function restoreTaskRecord(
  current: Task[] | undefined,
  previous: Task[] | undefined,
  taskId: string,
): Task[] | undefined {
  const previousTask = previous?.find((task) => task.id === taskId);
  const withoutTask = current?.filter((task) => task.id !== taskId);
  if (!previousTask) return withoutTask;
  if (!withoutTask) return previous;

  const previousIndex = previous?.findIndex((task) => task.id === taskId);
  const insertAt = Math.min(
    previousIndex ?? withoutTask.length,
    withoutTask.length,
  );
  return [
    ...withoutTask.slice(0, insertAt),
    previousTask,
    ...withoutTask.slice(insertAt),
  ];
}

function restoreTaskChannel(
  current: Task[] | undefined,
  previous: Task[] | undefined,
  taskId: string,
  optimisticChannelId: string,
): Task[] | undefined {
  const previousTask = previous?.find((task) => task.id === taskId);
  if (!previousTask) return current;
  return current?.map((task) =>
    task.id === taskId && task.channel === optimisticChannelId
      ? previousTask
      : task,
  );
}

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

  const invalidateTaskLists = (taskId: string) => {
    void queryClient.invalidateQueries({
      ...trpc.channelTasks.list.pathFilter(),
      predicate: (query) => {
        const tasks = query.state.data as ChannelTaskRecord[] | undefined;
        if (!tasks) return true;
        return tasks.some((record) => record.taskId === taskId);
      },
    });
  };

  const file = useMutation(
    trpc.channelTasks.file.mutationOptions({
      onMutate: async (variables) => {
        const filingToken = Symbol(variables.taskId);
        latestFilingsFor(queryClient).set(variables.taskId, filingToken);
        const listFilter = trpc.channelTasks.list.pathFilter();
        await Promise.all([
          queryClient.cancelQueries(listFilter),
          queryClient.cancelQueries({ queryKey: taskKeys.lists() }),
          queryClient.cancelQueries({ queryKey: channelFeedQueryRoot }),
          queryClient.cancelQueries({
            queryKey: taskKeys.detail(variables.taskId),
          }),
        ]);

        const previousQueries =
          queryClient.getQueriesData<ChannelTaskRecord[]>(listFilter);
        const previousTaskQueries = queryClient.getQueriesData<Task[]>({
          queryKey: taskKeys.lists(),
        });
        const previousTaskDetail = queryClient.getQueryData<Task>(
          taskKeys.detail(variables.taskId),
        );
        const previousChannelFeedQueries = queryClient.getQueriesData<Task[]>({
          queryKey: channelFeedQueryRoot,
        });
        const destinationFeedKey = channelFeedQueryKey(variables.channelId);
        const destinationFeedExisted =
          queryClient.getQueryState(destinationFeedKey) !== undefined;
        const destinationFilter = trpc.channelTasks.list.queryFilter({
          channelId: variables.channelId,
        });
        const destinationQueryExisted =
          queryClient.getQueryState(destinationFilter.queryKey) !== undefined;
        const previousRecord = previousQueries
          .flatMap(([, records]) => records ?? [])
          .find((record) => record.taskId === variables.taskId);
        const optimisticRecord: ChannelTaskRecord = {
          channelId: variables.channelId,
          taskId: variables.taskId,
          createdAt: previousRecord?.createdAt ?? Date.now(),
        };
        const optimisticTask = [
          previousTaskDetail,
          ...previousTaskQueries.flatMap(([, tasks]) => tasks ?? []),
          ...previousChannelFeedQueries.flatMap(([, tasks]) => tasks ?? []),
        ].find((task) => task?.id === variables.taskId);

        queryClient.setQueriesData<ChannelTaskRecord[]>(listFilter, (records) =>
          records?.filter((record) => record.taskId !== variables.taskId),
        );
        queryClient.setQueryDefaults(destinationFilter.queryKey, {
          meta: AUTH_SCOPED_QUERY_META,
        });
        queryClient.setQueryData<ChannelTaskRecord[]>(
          destinationFilter.queryKey,
          (records) => [...(records ?? []), optimisticRecord],
        );
        queryClient.setQueriesData<Task[]>(
          { queryKey: taskKeys.lists() },
          (tasks) =>
            tasks?.map((task) =>
              task.id === variables.taskId
                ? { ...task, channel: variables.channelId }
                : task,
            ),
        );
        queryClient.setQueryData<Task>(
          taskKeys.detail(variables.taskId),
          (task) =>
            task ? { ...task, channel: variables.channelId } : undefined,
        );
        queryClient.setQueriesData<Task[]>(
          { queryKey: channelFeedQueryRoot },
          (tasks) => tasks?.filter((task) => task.id !== variables.taskId),
        );
        if (destinationFeedExisted && optimisticTask) {
          queryClient.setQueryData<Task[]>(destinationFeedKey, (tasks) => [
            ...(tasks ?? []).filter((task) => task.id !== variables.taskId),
            { ...optimisticTask, channel: variables.channelId },
          ]);
        }

        const affectedQueryKeys = previousQueries
          .filter(
            ([, records]) =>
              !records ||
              records.some((record) => record.taskId === variables.taskId),
          )
          .map(([queryKey]) => queryKey);

        return {
          affectedQueryKeys,
          filingToken,
          destinationFilter,
          destinationQueryExisted,
          previousChannelFeedQueries,
          previousQueries,
          previousTaskDetail,
          previousTaskQueries,
        };
      },
      onSuccess: (record, variables, context) => {
        if (
          !context ||
          latestFilingsFor(queryClient).get(variables.taskId) !==
            context.filingToken
        ) {
          return;
        }
        queryClient.setQueryData<ChannelTaskRecord[]>(
          context.destinationFilter.queryKey,
          (records) =>
            records?.map((current) =>
              current.taskId === variables.taskId &&
              current.channelId === variables.channelId
                ? record
                : current,
            ),
        );
      },
      onError: (_error, variables, context) => {
        if (
          !context ||
          latestFilingsFor(queryClient).get(variables.taskId) !==
            context.filingToken
        ) {
          return;
        }
        const destinationRecords = queryClient.getQueryData<
          ChannelTaskRecord[]
        >(context.destinationFilter.queryKey);
        const ownsOptimisticMove = destinationRecords?.some(
          (record) =>
            record.taskId === variables.taskId &&
            record.channelId === variables.channelId,
        );
        if (!ownsOptimisticMove) return;

        for (const [queryKey, previousRecords] of context.previousQueries) {
          queryClient.setQueryData<ChannelTaskRecord[]>(queryKey, (current) =>
            restoreChannelTaskRecord(
              current,
              previousRecords,
              variables.taskId,
            ),
          );
        }
        for (const [queryKey, previousTasks] of context.previousTaskQueries) {
          queryClient.setQueryData<Task[]>(queryKey, (current) =>
            restoreTaskChannel(
              current,
              previousTasks,
              variables.taskId,
              variables.channelId,
            ),
          );
        }
        for (const [
          queryKey,
          previousTasks,
        ] of context.previousChannelFeedQueries) {
          queryClient.setQueryData<Task[]>(queryKey, (current) =>
            restoreTaskRecord(current, previousTasks, variables.taskId),
          );
        }
        queryClient.setQueryData<Task>(
          taskKeys.detail(variables.taskId),
          (current) =>
            current?.channel === variables.channelId
              ? context.previousTaskDetail
              : current,
        );
        if (!context.destinationQueryExisted) {
          queryClient.setQueryData<ChannelTaskRecord[]>(
            context.destinationFilter.queryKey,
            (current) =>
              current?.filter((record) => record.taskId !== variables.taskId),
          );
          const current = queryClient.getQueryData<ChannelTaskRecord[]>(
            context.destinationFilter.queryKey,
          );
          if (!current || current.length === 0) {
            queryClient.removeQueries({
              queryKey: context.destinationFilter.queryKey,
              exact: true,
            });
          }
        }
      },
      onSettled: (_data, _error, variables, context) => {
        if (
          !context ||
          latestFilingsFor(queryClient).get(variables.taskId) !==
            context.filingToken
        ) {
          return;
        }
        latestFilingsFor(queryClient).delete(variables.taskId);
        for (const queryKey of [
          ...context.affectedQueryKeys,
          context.destinationFilter.queryKey,
        ]) {
          void queryClient.invalidateQueries({ queryKey, exact: true });
        }
        void queryClient.invalidateQueries({ queryKey: channelFeedQueryRoot });
        void queryClient.invalidateQueries({ queryKey: taskKeys.lists() });
        void queryClient.invalidateQueries({
          queryKey: taskKeys.detail(variables.taskId),
        });
      },
    }),
  );
  const unfile = useMutation(
    trpc.channelTasks.unfile.mutationOptions({
      onSuccess: (_data, variables) => invalidateTaskLists(variables.taskId),
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
