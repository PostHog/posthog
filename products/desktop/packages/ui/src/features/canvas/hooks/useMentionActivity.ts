import {
  type MentionActivityItem,
  mergeTaskMentions,
  toMentionActivityItems,
} from "@posthog/core/canvas/mentionActivity";
import type { TaskMention } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

const ACTIVITY_POLL_INTERVAL_MS = 60_000;
const TASK_MENTIONS_QUERY_KEY = ["task-mentions"] as const;

/**
 * Thread messages across all channels that @-mention the current user,
 * newest first, from the backend mentions index. Mount once per surface
 * (sidebar badge, Activity page) — results are shared through the
 * react-query cache.
 */
export function useMentionActivity(options?: { enabled?: boolean }): {
  items: MentionActivityItem[];
  isLoading: boolean;
} {
  const queryClient = useQueryClient();
  const query = useAuthenticatedQuery(
    TASK_MENTIONS_QUERY_KEY,
    async (client) => {
      const previous =
        queryClient.getQueryData<TaskMention[]>(TASK_MENTIONS_QUERY_KEY) ?? [];
      // Newest mention already held becomes the low-water mark, so repolls
      // ask the backend only for what's new instead of the whole top page.
      const since = previous[0]?.created_at;
      const incoming = await client.getTaskMentions(
        since ? { since } : undefined,
      );
      return mergeTaskMentions(previous, incoming);
    },
    {
      enabled: options?.enabled ?? true,
      refetchInterval: ACTIVITY_POLL_INTERVAL_MS,
      staleTime: ACTIVITY_POLL_INTERVAL_MS,
    },
  );
  const items = useMemo(
    () => toMentionActivityItems(query.data ?? []),
    [query.data],
  );
  return { items, isLoading: query.isLoading };
}
