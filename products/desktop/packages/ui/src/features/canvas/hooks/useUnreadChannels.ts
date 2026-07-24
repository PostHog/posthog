import { unreadChannelIds } from "@posthog/core/canvas/channelUnread";
import { useMentionActivity } from "@posthog/ui/features/canvas/hooks/useMentionActivity";
import {
  normalizeChannelName,
  PERSONAL_CHANNEL_NAME,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelSeenStore } from "@posthog/ui/features/canvas/stores/channelSeenStore";
import { useMemo } from "react";

const NONE: ReadonlySet<string> = new Set();

/**
 * Backend channel ids with activity the viewer hasn't seen. Shares the mentions
 * query with the Activity badge through the react-query cache, so mounting this
 * in the sidebar costs no extra fetch.
 *
 * Nothing is unread until the seen map is back from storage: an empty map reads
 * exactly like "never opened anything", which would bold every channel with
 * activity for the first frames of every boot.
 */
export function useUnreadChannelIds(): ReadonlySet<string> {
  const { items } = useMentionActivity();
  const lastSeenByChannel = useChannelSeenStore((s) => s.lastSeenByChannel);
  const hasHydrated = useChannelSeenStore((s) => s.hasHydrated);
  return useMemo(
    () => (hasHydrated ? unreadChannelIds(items, lastSeenByChannel) : NONE),
    [items, lastSeenByChannel, hasHydrated],
  );
}

/**
 * Is this folder channel unread, by display name?
 *
 * Unread is keyed by backend channel id while the sidebar's rows are folder
 * channels, so something has to bridge the two. This mirrors the mapping
 * useBackendChannel walks — "me" is the personal channel (matched by type, as
 * its name is the backend's business), everything else matches a public channel
 * by normalized name — and does it once for the whole list rather than
 * resolving per row, which would fire a resolve per channel.
 */
export function useIsChannelUnread(): (channelName: string) => boolean {
  const { channels: backendChannels, personalChannel } = useTaskChannels();
  const unreadIds = useUnreadChannelIds();

  return useMemo(() => {
    const unreadNames = new Set<string>();
    for (const channel of backendChannels) {
      if (channel.channel_type === "public" && unreadIds.has(channel.id)) {
        unreadNames.add(channel.name);
      }
    }
    const personalUnread =
      !!personalChannel && unreadIds.has(personalChannel.id);
    return (channelName: string) => {
      const normalized = normalizeChannelName(channelName);
      return normalized === PERSONAL_CHANNEL_NAME
        ? personalUnread
        : unreadNames.has(normalized);
    };
  }, [backendChannels, personalChannel, unreadIds]);
}
