import { latestActivityForChannel } from "@posthog/core/canvas/channelUnread";
import { useMentionActivity } from "@posthog/ui/features/canvas/hooks/useMentionActivity";
import { useChannelSeenStore } from "@posthog/ui/features/canvas/stores/channelSeenStore";
import { useEffect } from "react";

/**
 * Looking at a channel reads it: stamp it seen so the sidebar drops its bold.
 *
 * Main channel surfaces call this through ChannelHeader. The sidebar calls it
 * separately while its channel pane is visible because opening that pane does
 * not navigate the main window.
 *
 * Stamped with the newest activity rather than "now": a mention landing while
 * you're looking re-stamps it, remounts don't churn the store, and the store
 * can't record having seen something that hasn't happened yet.
 */
export function useMarkChannelSeen(channelId: string | undefined): void {
  const { items: mentionItems } = useMentionActivity();
  const markChannelSeen = useChannelSeenStore((s) => s.markChannelSeen);
  // Writing before the persisted map lands would be merged against an empty
  // map; the store folds the two, but waiting keeps the write ordered behind
  // the read it is meant to supersede.
  const hasHydrated = useChannelSeenStore((s) => s.hasHydrated);

  const latestActivityAt = latestActivityForChannel(mentionItems, channelId);

  useEffect(() => {
    if (!hasHydrated || !channelId || !latestActivityAt) return;
    markChannelSeen(channelId, latestActivityAt);
  }, [hasHydrated, channelId, latestActivityAt, markChannelSeen]);
}
