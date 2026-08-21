import type {
  TaskActivity,
  TaskActivityMarkUnreadResult,
  TaskActivityPage,
  TaskActivityReadMarker,
} from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { TASK_ACTIVITY_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { toast } from "@posthog/ui/primitives/toast";
import type { InfiniteData, UseMutationResult } from "@tanstack/react-query";
import { useMutation, useQueryClient } from "@tanstack/react-query";

interface MarkUnreadContext {
  previous?: InfiniteData<TaskActivityPage>;
}

export function useMarkTaskActivityUnread(): UseMutationResult<
  TaskActivityMarkUnreadResult | undefined,
  Error,
  TaskActivityReadMarker[],
  MarkUnreadContext
> {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (activities: TaskActivityReadMarker[]) => {
      if (!client) throw new Error("Not authenticated");
      if (activities.length === 0) return;
      return client.markTaskActivityUnread(activities);
    },
    onMutate: async (activities: TaskActivityReadMarker[]) => {
      await queryClient.cancelQueries({ queryKey: TASK_ACTIVITY_QUERY_KEY });
      const previous = queryClient.getQueryData<InfiniteData<TaskActivityPage>>(
        TASK_ACTIVITY_QUERY_KEY,
      );
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
          const shouldMarkUnread = (row: TaskActivity): boolean => {
            const seenBefore = markedTasks.get(row.task_id);
            return (
              markedCommentActivities.has(row.id) ||
              (!row.latest_comment_id &&
                !!seenBefore &&
                row.activity_at <= seenBefore)
            );
          };
          let restored = 0;
          for (const page of data.pages) {
            for (const row of page.results) {
              if (!row.is_unread && shouldMarkUnread(row)) restored++;
            }
          }
          return {
            ...data,
            pages: data.pages.map((page, index) => ({
              ...page,
              unread_count:
                index === 0 ? page.unread_count + restored : page.unread_count,
              results: page.results.map((row) =>
                shouldMarkUnread(row) ? { ...row, is_unread: true } : row,
              ),
            })),
          };
        },
      );
      return { previous };
    },
    onError: (_error, _activities, context) => {
      if (context?.previous) {
        queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, context.previous);
      }
      toast.error("Couldn't mark activity as unread");
    },
  });
}
