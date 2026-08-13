import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";

/**
 * Whether the channels world is on: the new channels layout, or the alpha
 * channel list toggled on under project-bluebird. This is the exact gate
 * ChannelsSidebar mounts the channel list under, which makes it the signal
 * that the list's org-wide task poll (space badges) is running.
 */
export function useChannelsWorld(): boolean {
  const channelsLayout = useChannelsLayout();
  const bluebirdEnabled = useBluebirdFlag();
  const channelsToggleOn = useSidebarStore((s) => s.channelsEnabled);
  return channelsLayout || (channelsToggleOn && bluebirdEnabled);
}
