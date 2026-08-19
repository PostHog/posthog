import type { Task } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

// Slower than a channel feed's 5s: a feed query searches the whole project's
// tasks rather than one channel, and a saved view can afford to lag a little.
const TASK_FEED_POLL_INTERVAL_MS = 15_000;

export function taskFeedResultsQueryKey(query: string) {
  return ["task-feed-results", query] as const;
}

/**
 * The tasks a custom feed's query matches right now, newest handled by the
 * feed view's own ordering. Results are the live task list filtered
 * server-side — the feed stores a query, never task ids, so a task that stops
 * matching simply stops appearing.
 */
export function useTaskFeedResults(query: string | undefined): {
  tasks: Task[];
  isLoading: boolean;
} {
  const normalized = query?.trim() ?? "";
  const result = useAuthenticatedQuery<Task[]>(
    taskFeedResultsQueryKey(normalized),
    (client) =>
      client.getTasks({ search: normalized }) as unknown as Promise<Task[]>,
    {
      enabled: normalized !== "",
      gcTime: SPACE_QUERY_GC_TIME_MS,
      refetchInterval: TASK_FEED_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    },
  );
  return { tasks: result.data ?? [], isLoading: result.isLoading };
}
