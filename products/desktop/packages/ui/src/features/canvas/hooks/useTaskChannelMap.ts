import { useHostTRPC } from "@posthog/host-router/react";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";

/**
 * Map of taskId → the channel it's filed to. A task is filed to at most one
 * channel (ChannelTasksService moves the row rather than duplicating it), so
 * the mapping is unambiguous. Fans out one `channelTasks.list` query per
 * channel; results are shared with the channel sidebar's per-section queries
 * through the react-query cache.
 *
 * Takes the already-fetched `channels` rather than subscribing to `useChannels`
 * itself, so the caller owns the single subscription and a stable reference.
 */
export function useTaskChannelMap(
  channels: Channel[],
  options?: { enabled?: boolean },
): Map<string, Channel> {
  const enabled = options?.enabled ?? true;
  const trpc = useHostTRPC();
  const results = useQueries({
    queries: channels.map((channel) =>
      trpc.channelTasks.list.queryOptions(
        { channelId: channel.id },
        { enabled, staleTime: 5_000 },
      ),
    ),
  });
  return useMemo(() => {
    const map = new Map<string, Channel>();
    results.forEach((res, i) => {
      const channel = channels[i];
      if (!channel) return;
      for (const record of res.data ?? []) {
        if (record.taskId) map.set(record.taskId, channel);
      }
    });
    return map;
  }, [results, channels]);
}
