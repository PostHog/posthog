import { latestActivityForChannel } from "@posthog/core/canvas/channelUnread";
import { useMentionActivity } from "@posthog/ui/features/canvas/hooks/useMentionActivity";
import { useBackendChannel } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelSeenStore } from "@posthog/ui/features/canvas/stores/channelSeenStore";
import { useEffect } from "react";

/**
 * Looking at a channel reads it: stamp it seen so the sidebar drops its bold.
 *
 * Called from ChannelHeader, which every channel surface renders — the feed,
 * Artifacts, Recents and CONTEXT.md all count as being in the channel, and
 * hanging this off the header means a new surface gets it for free rather than
 * having to remember.
 *
 * Stamped with the newest activity rather than "now": a mention landing while
 * you're looking re-stamps it, remounts don't churn the store, and the store
 * can't record having seen something that hasn't happened yet.
 */
export function useMarkChannelSeen(channelName: string | undefined): void {
  const { channel: backendChannel } = useBackendChannel(channelName);
  const { items: mentionItems } = useMentionActivity();
  const markChannelSeen = useChannelSeenStore((s) => s.markChannelSeen);
  // Writing before the persisted map lands would be merged against an empty
  // map; the store folds the two, but waiting keeps the write ordered behind
  // the read it is meant to supersede.
  const hasHydrated = useChannelSeenStore((s) => s.hasHydrated);

  const backendChannelId = backendChannel?.id;
  const latestActivityAt = latestActivityForChannel(
    mentionItems,
    backendChannelId,
  );

  useEffect(() => {
    if (!hasHydrated || !backendChannelId || !latestActivityAt) return;
    markChannelSeen(backendChannelId, latestActivityAt);
  }, [hasHydrated, backendChannelId, latestActivityAt, markChannelSeen]);
}
