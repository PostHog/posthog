import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

const log = logger.scope("pinned-tasks");

/** Mirrors desktop's sidebar pin cache key semantics: per-user, server-synced
 *  via /tasks/pinned/. Project switches clear the query cache wholesale
 *  (authStore.setProjectId), so no project id in the key. */
export const pinnedTaskKeys = {
  all: ["task-pins"] as const,
};

export function usePinnedTasks() {
  const { projectId, oauthAccessToken } = useAuthStore();
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: pinnedTaskKeys.all,
    queryFn: () => getPostHogApiClient().getPinnedTaskIds(),
    enabled: !!projectId && !!oauthAccessToken,
    staleTime: 30_000,
  });

  const pinnedTaskIds = query.data ?? [];
  const pinnedSet = useMemo(() => new Set(pinnedTaskIds), [pinnedTaskIds]);

  const toggleMutation = useMutation({
    mutationFn: ({ taskId, pinned }: { taskId: string; pinned: boolean }) =>
      getPostHogApiClient().setTaskPinned(taskId, pinned),
    onMutate: async ({ taskId, pinned }) => {
      await queryClient.cancelQueries({ queryKey: pinnedTaskKeys.all });
      const previous = queryClient.getQueryData<string[]>(pinnedTaskKeys.all);
      queryClient.setQueryData<string[]>(pinnedTaskKeys.all, (old) => {
        const filtered = old?.filter((id) => id !== taskId) ?? [];
        // Server returns newest pins first, so an optimistic pin goes to
        // the front to match what the next refetch will say.
        return pinned ? [taskId, ...filtered] : filtered;
      });
      return { previous };
    },
    onError: (error, { taskId }, context) => {
      log.warn("Toggling pin failed; rolled back", {
        taskId,
        error: error.message,
      });
      if (context?.previous) {
        queryClient.setQueryData(pinnedTaskKeys.all, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: pinnedTaskKeys.all });
    },
  });

  const { mutate: toggleMutate } = toggleMutation;
  const togglePin = useCallback(
    (taskId: string) => {
      toggleMutate({ taskId, pinned: !pinnedSet.has(taskId) });
    },
    [toggleMutate, pinnedSet],
  );

  const isPinned = useCallback(
    (taskId: string) => pinnedSet.has(taskId),
    [pinnedSet],
  );

  return {
    pinnedTaskIds,
    isPinned,
    togglePin,
    isLoading: query.isLoading,
    /** The list reflects the server. An empty list before this is not "nothing
     *  is pinned", so callers that delete on absence must wait for it. */
    hasLoaded: query.isSuccess,
  };
}
