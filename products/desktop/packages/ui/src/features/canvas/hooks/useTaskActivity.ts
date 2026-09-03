import {
  type TaskActivityItem,
  toTaskActivityItems,
} from "@posthog/core/canvas/taskActivity";
import type { TaskActivityPage } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { TASK_ACTIVITY_QUERY_KEY } from "../task-activity/taskActivityQuery";

export { TASK_ACTIVITY_QUERY_KEY } from "../task-activity/taskActivityQuery";

const TASK_ACTIVITY_REFETCH_INTERVAL_MS = 60_000;

/**
 * Task lifecycle and comment activity for the current user, newest first. Task
 * lifecycle rows collapse per task while comment notifications remain separate.
 * Mount once per surface (sidebar badge, Activity page); results are
 * shared through the react-query cache.
 */
export function useTaskActivity(options?: { enabled?: boolean }): {
  items: TaskActivityItem[];
  unreadCount: number;
  isLoading: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => Promise<unknown>;
} {
  const client = useOptionalAuthenticatedClient();
  const query = useInfiniteQuery({
    queryKey: TASK_ACTIVITY_QUERY_KEY,
    queryFn: ({ pageParam }) => {
      if (!client) throw new Error("Not authenticated");
      return client.getTaskActivity(pageParam);
    },
    initialPageParam: undefined as
      | { before: string; beforeId: string }
      | undefined,
    getNextPageParam: (page: TaskActivityPage) =>
      page.next_before && page.next_before_id
        ? { before: page.next_before, beforeId: page.next_before_id }
        : undefined,
    enabled: !!client && (options?.enabled ?? true),
    staleTime: TASK_ACTIVITY_REFETCH_INTERVAL_MS,
    refetchInterval: TASK_ACTIVITY_REFETCH_INTERVAL_MS,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    meta: AUTH_SCOPED_QUERY_META,
  });
  const items = useMemo(
    () =>
      toTaskActivityItems(
        query.data?.pages.flatMap((page) => page.results) ?? [],
      ),
    [query.data],
  );
  return {
    items,
    unreadCount: query.data?.pages[0]?.unread_count ?? 0,
    isLoading: query.isLoading,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    fetchNextPage: query.fetchNextPage,
  };
}
