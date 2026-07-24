import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

/** Tasks filed to a channel — backed by desktop_file_system rows. */
export function useChannelTasks(channelId: string | undefined): {
  tasks: ChannelTaskRecord[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.channelTasks.list.queryOptions(
      { channelId: channelId ?? "" },
      { enabled: !!channelId, staleTime: 5_000 },
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
          { staleTime: 5_000 },
        ),
      );
    },
    [trpc, queryClient],
  );
}

export function useChannelTaskMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const invalidate = () => {
    void queryClient.invalidateQueries(trpc.channelTasks.list.pathFilter());
  };

  const file = useMutation(
    trpc.channelTasks.file.mutationOptions({ onSuccess: invalidate }),
  );
  const unfile = useMutation(
    trpc.channelTasks.unfile.mutationOptions({ onSuccess: invalidate }),
  );

  return {
    fileTask: (channelId: string, taskId: string, taskTitle: string) =>
      file.mutateAsync({ channelId, taskId, taskTitle }),
    unfileTask: (id: string) => unfile.mutateAsync({ id }),
    isFiling: file.isPending,
    isUnfiling: unfile.isPending,
  };
}
