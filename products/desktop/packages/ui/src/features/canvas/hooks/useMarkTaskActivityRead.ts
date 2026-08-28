import type {
  TaskActivityPage,
  TaskActivityReadMarker,
} from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { TASK_ACTIVITY_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import type { InfiniteData } from "@tanstack/react-query";
import { useMutation, useQueryClient } from "@tanstack/react-query";

/**
 * Clear the unread flag on specific tasks. Read state lives per task on the server,
 * so this is also what the server does when the user reaches a task by any other
 * route — the optimistic update here just saves a round trip.
 */
export function useMarkTaskActivityRead() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (activities: TaskActivityReadMarker[]) => {
      if (!client) throw new Error("Not authenticated");
      if (activities.length === 0) return;
      return client.markTaskActivityRead(activities);
    },
    onMutate: async (activities: TaskActivityReadMarker[]) => {
      const markedTasks = new Map(
        activities.flatMap((activity) =>
          activity.activity_id
            ? []
            : [[activity.task_id, activity.seen_before] as const],
        ),
      );
      const markedCommentActivities = new Set(
        activities.flatMap((activity) =>
          activity.activity_id ? [activity.activity_id] : [],
        ),
      );
      queryClient.setQueryData<InfiniteData<TaskActivityPage>>(
        TASK_ACTIVITY_QUERY_KEY,
        (data) => {
          if (!data) return data;
          const clearing = data.pages
            .flatMap((page) => page.results)
            .filter((row) => {
              const seenBefore = markedTasks.get(row.task_id);
              return (
                row.is_unread &&
                (markedCommentActivities.has(row.id) ||
                  (!row.latest_comment_id &&
                    !!seenBefore &&
                    row.activity_at <= seenBefore))
              );
            }).length;
          return {
            ...data,
            pages: data.pages.map((page, index) => ({
              ...page,
              unread_count:
                index === 0
                  ? Math.max(0, page.unread_count - clearing)
                  : page.unread_count,
              results: page.results.map((row) => {
                const seenBefore = markedTasks.get(row.task_id);
                return markedCommentActivities.has(row.id) ||
                  (!row.latest_comment_id &&
                    !!seenBefore &&
                    row.activity_at <= seenBefore)
                  ? { ...row, is_unread: false }
                  : row;
              }),
            })),
          };
        },
      );
    },
  });
}
