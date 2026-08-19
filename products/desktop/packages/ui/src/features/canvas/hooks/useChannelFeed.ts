import type { Task } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

// Feeds are multiplayer: poll fast enough that a teammate's new task card and
// run-status flips feel live without a dedicated push channel.
const CHANNEL_FEED_POLL_INTERVAL_MS = 5_000;
export const channelFeedQueryRoot = ["channel-feed"] as const;

export function channelFeedQueryKey(channelId: string | undefined) {
  return [...channelFeedQueryRoot, channelId ?? "none"] as const;
}

/**
 * A channel's task feed, oldest first (Slack ordering — the composer sits at
 * the bottom and new cards land above it).
 */
export function useChannelFeed(channelId: string | undefined): {
  tasks: Task[];
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<Task[]>(
    channelFeedQueryKey(channelId),
    (client) =>
      // Order the server page by activity, not creation. The feed is capped
      // server-side, so a long-running but old session would fall off a
      // created-first page before the activity sort could surface it. The rows
      // are still shown oldest-first below; this only decides which tasks make
      // the page.
      client.getTasks({
        channel: channelId,
        ordering: "-last_activity_at",
      }) as unknown as Promise<Task[]>,
    {
      enabled: !!channelId,
      gcTime: SPACE_QUERY_GC_TIME_MS,
      refetchInterval: CHANNEL_FEED_POLL_INTERVAL_MS,
      staleTime: SPACE_QUERY_STALE_TIME_MS,
    },
  );
  const tasks = useMemo(
    () =>
      [...(query.data ?? [])].sort((a, b) =>
        a.created_at.localeCompare(b.created_at),
      ),
    [query.data],
  );
  return { tasks, isLoading: query.isLoading };
}
