import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useActiveSession } from "@posthog/ui/features/navigation/useActiveSession";

/**
 * Whether a session's review belongs to the shared right panel rather than to
 * the surface asking. Keyed on the session, not the route's channel: Activity
 * puts no channel in the URL, and asking for one there left both surfaces
 * drawing the diff.
 */
export function useReviewInRightPanel(): boolean {
  const { taskId } = useActiveSession();
  return useChannelsLayout() && taskId != null;
}
