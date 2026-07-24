import type { Task } from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

// Feeds are multiplayer: poll fast enough that a teammate's new task card and
// run-status flips feel live without a dedicated push channel.
const CHANNEL_FEED_POLL_INTERVAL_MS = 5_000;

export function channelFeedQueryKey(channelId: string | undefined) {
  return ["channel-feed", channelId ?? "none"] as const;
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
      client.getTasks({ channel: channelId }) as unknown as Promise<Task[]>,
    {
      enabled: !!channelId,
      refetchInterval: CHANNEL_FEED_POLL_INTERVAL_MS,
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
