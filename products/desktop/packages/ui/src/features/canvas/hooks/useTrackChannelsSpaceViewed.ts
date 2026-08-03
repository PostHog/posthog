import {
  ANALYTICS_EVENTS,
  type SidebarLayout,
} from "@posthog/shared/analytics-events";
import { useChannelStars } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

export function useTrackChannelsSpaceViewed({
  enabled,
  layout,
}: {
  enabled: boolean;
  layout: SidebarLayout;
}): void {
  const { channels: allChannels, isLoading } = useChannels({ enabled });
  const { starredRefToShortcutId } = useChannelStars();

  const shared = allChannels.filter(
    (c: Channel) => c.name !== PERSONAL_CHANNEL_NAME,
  );
  const channelCount = shared.length;
  const starredCount = shared.filter((c: Channel) =>
    starredRefToShortcutId.has(c.path),
  ).length;

  const trackedRef = useRef(false);
  useEffect(() => {
    if (!enabled) {
      trackedRef.current = false;
      return;
    }
    if (isLoading || trackedRef.current) return;
    trackedRef.current = true;
    track(ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED, {
      channel_count: channelCount,
      starred_count: starredCount,
      layout,
    });
  }, [enabled, isLoading, channelCount, starredCount, layout]);
}
