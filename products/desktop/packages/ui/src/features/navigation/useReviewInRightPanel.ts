import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useParams } from "@tanstack/react-router";

/**
 * Whether a session's review belongs to the shared right panel rather than to
 * the surface asking. Three places turn on this: the panel draws the review,
 * the session's own review pane stands down, and the controls that opened the
 * review from elsewhere come off, because the panel's switcher owns it now.
 */
export function useReviewInRightPanel(): boolean {
  const channelId = useParams({ strict: false }).channelId;
  return useChannelsLayout() && channelId != null;
}
