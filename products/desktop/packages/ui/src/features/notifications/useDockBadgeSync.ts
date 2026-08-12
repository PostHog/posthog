import { useServiceOptional } from "@posthog/di/react";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import { useTaskActivity } from "@posthog/ui/features/canvas/hooks/useTaskActivity";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useEffect } from "react";

/**
 * Mirrors the unread task-activity count onto the host's app badge (the macOS
 * dock tile, or the Badging API on web).
 *
 * The badge tracks the count rather than reacting to notification events,
 * because `NotificationBus` decides where a notification goes from whether the
 * app was focused at the instant it fired. Anything that arrived while the user
 * was looking at the app never reached the dock under that rule, which is why
 * the badge was effectively invisible.
 */
export function useDockBadgeSync(): void {
  const { unreadCount } = useTaskActivity();
  const enabled = useSettingsStore((s) => s.dockBadgeNotifications);
  // Optional so hosts that bind no notifier (or a test container) no-op instead
  // of throwing at the top of the app tree.
  const notifications = useServiceOptional<INotifications>(
    NOTIFICATIONS_SERVICE,
  );
  const count = enabled ? unreadCount : 0;

  useEffect(() => {
    notifications?.setUnreadCount(count);
  }, [notifications, count]);

  useEffect(
    () => () => {
      // Signing out unmounts this, and a stale number on the dock would outlive
      // the session it came from.
      notifications?.setUnreadCount(0);
    },
    [notifications],
  );
}

// Renders nothing; exists to own the only task-activity subscription that is
// guaranteed to be alive. The sidebar's Activity row unmounts on the settings
// route, when the user hides that row, and when project-bluebird is off, so the
// badge cannot depend on it.
export function DockBadgeSync(): null {
  useDockBadgeSync();
  return null;
}
