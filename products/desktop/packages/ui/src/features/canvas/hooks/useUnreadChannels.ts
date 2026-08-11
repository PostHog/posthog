import { unreadChannelIds } from "@posthog/core/canvas/channelUnread";
import { useMentionActivity } from "@posthog/ui/features/canvas/hooks/useMentionActivity";
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
 * Is this channel unread, by id? Unread and the sidebar rows share the backend
 * channel id, so this is a straight set lookup — `undefined` (a row whose
 * channel hasn't loaded yet) is never unread.
 */
export function useIsChannelUnread(): (
  channelId: string | undefined,
) => boolean {
  const unreadIds = useUnreadChannelIds();
  return useMemo(
    () => (channelId) => !!channelId && unreadIds.has(channelId),
    [unreadIds],
  );
}
