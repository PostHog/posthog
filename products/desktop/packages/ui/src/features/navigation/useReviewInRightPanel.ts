import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useActiveSession } from "@posthog/ui/features/navigation/useActiveSession";

/**
 * Whether a session's review belongs to the shared right panel rather than to
 * the surface asking. Three places turn on this: the panel draws the review,
 * the session's own review pane stands down, and the controls that opened the
 * review from elsewhere come off, because the panel's switcher owns it now.
 *
 * Keyed on the session rather than the route's channel. Activity reads a task
 * into the content pane without routing to it, so there is no channel in the
 * URL to find — and asking for one there left both surfaces believing they had
 * to draw the diff.
 */
export function useReviewInRightPanel(): boolean {
  const { taskId } = useActiveSession();
  return useChannelsLayout() && taskId != null;
}
