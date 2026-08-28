import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  resetCurrentChannel,
  useCurrentChannelStore,
} from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useEffect } from "react";

/**
 * The scoped channel, resolved against the project's live channel list.
 *
 * Sole owner of the invariant "the current channel is a channel that exists in
 * the current project". The store is a bare id with no project affinity, so a
 * project switch, a channel deletion, or a route pointing at something stale
 * would otherwise leave it naming a channel nobody can load — and
 * `openTaskInput` files new tasks against whatever it holds.
 *
 * Self-heals rather than validating at each read site: `openTaskInput` runs
 * outside React and can't see the channel list, and by the time the auth side
 * effects call it the query cache has already been cleared.
 */
export function useCurrentChannel({ enabled }: { enabled: boolean }): {
  currentChannelId: string | null;
  channels: Channel[];
} {
  const storedChannelId = useCurrentChannelStore((s) => s.currentChannelId);
  const { channels, isLoading } = useChannels({ enabled });

  const currentChannel = storedChannelId
    ? channels.find((c) => c.id === storedChannelId)
    : undefined;
  // A pending list is not evidence of absence — only clear once we've actually
  // seen the project's channels and this one wasn't among them.
  const isStale = storedChannelId != null && !isLoading && !currentChannel;

  useEffect(() => {
    if (!enabled || isStale) resetCurrentChannel();
  }, [enabled, isStale]);

  return {
    // Never hand back an id we couldn't resolve, so callers can't navigate to
    // or file against a dead channel in the window before the effect runs.
    currentChannelId: currentChannel?.id ?? null,
    channels,
  };
}
