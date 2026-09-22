import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";

/** Whether the tab strip owns navigation inside the spaces layout. */
export function useSpacesTabs(): boolean {
  return useChannelsLayout();
}
