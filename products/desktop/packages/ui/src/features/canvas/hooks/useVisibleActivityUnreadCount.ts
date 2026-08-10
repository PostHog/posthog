import {
  getUnreadActivityItems,
  getVisibleActivityItems,
  visibleActivityUnreadCount,
} from "@posthog/ui/features/canvas/components/activityFeed";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { useMemo } from "react";

/**
 * The unread total for the Activity badges, counted the same way the feed filters
 * itself. Reading the server count straight would leave a badge sitting on an
 * unread the feed hides, with nothing the viewer can open to clear it.
 */
export function useVisibleActivityUnreadCount(): number {
  const commentsEnabled = useCommentsEnabled();
  const { items, unreadCount } = useTaskActivity();
  return useMemo(
    () =>
      visibleActivityUnreadCount({
        commentsEnabled,
        unreadCount,
        loadedVisibleUnread: getUnreadActivityItems(
          getVisibleActivityItems(items, commentsEnabled),
        ).length,
      }),
    [commentsEnabled, items, unreadCount],
  );
}
