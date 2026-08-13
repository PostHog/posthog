import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useBluebirdFlag } from "@posthog/ui/features/feature-flags/useBluebirdFlag";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";

export function useChannelsWorld(): boolean {
  const channelsLayout = useChannelsLayout();
  const bluebirdEnabled = useBluebirdFlag();
  const channelsToggleOn = useSidebarStore((s) => s.channelsEnabled);
  return channelsLayout || (channelsToggleOn && bluebirdEnabled);
}
