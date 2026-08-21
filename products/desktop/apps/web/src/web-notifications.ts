import type {
  INotifications,
  NotificationOptions,
  NotificationTarget,
} from "@posthog/platform/notifications";
import type {
  IActiveView,
  INotificationSettings,
  NotificationSettings,
} from "@posthog/ui/features/notifications/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  getCurrentMatches,
  openNotificationTarget,
} from "@posthog/ui/router/navigationBridge";

// The Web Notifications API is the browser equivalent of the desktop main
// process's OS notifications. Clicking a notification focuses the tab and
// navigates to its target (the in-app equivalent of a desktop deep link).
function showNotification(options: NotificationOptions): void {
  const notification = new Notification(options.title, {
    body: options.body,
    silent: options.silent,
  });
  const target = options.target;
  if (target) {
    notification.onclick = () => {
      window.focus();
      openNotificationTarget(target);
      notification.close();
    };
  }
}

export const webNotifications: INotifications = {
  notify(options: NotificationOptions): void {
    if (typeof Notification === "undefined") return;
    // Show immediately when already granted. When the browser hasn't been asked
    // yet (permission "default"), request it and show on grant — this makes the
    // settings test button work standalone, and prompts on the first real
    // notification. "denied" is respected (no prompt, no notification).
    if (Notification.permission === "granted") {
      showNotification(options);
    } else if (Notification.permission === "default") {
      void Notification.requestPermission().then((permission) => {
        if (permission === "granted") showNotification(options);
      });
    }
  },

  // Web equivalent of a dock badge: the Badging API (installed PWAs). No-op
  // where unsupported.
  showUnreadIndicator(): void {
    const setAppBadge = (
      navigator as Navigator & { setAppBadge?: () => Promise<void> }
    ).setAppBadge;
    void setAppBadge?.call(navigator).catch(() => {});
  },

  // No browser equivalent of bouncing a dock icon.
  requestAttention(): void {},
};

// Host-agnostic: reads the same settings store desktop does.
export const webNotificationSettings: INotificationSettings = {
  get(): NotificationSettings {
    const s = useSettingsStore.getState();
    return {
      desktopNotifications: s.desktopNotifications,
      dockBadgeNotifications: s.dockBadgeNotifications,
      dockBounceNotifications: s.dockBounceNotifications,
      completionSound: s.completionSound,
      completionVolume: s.completionVolume,
      scaleSoundWithTaskLength: s.scaleSoundWithTaskLength,
      customSounds: s.customSounds,
    };
  },
};

// Host-agnostic: reads the active leaf route to suppress notifications for the
// task/canvas already on screen. Mirrors the desktop renderer adapter.
export const webActiveView: IActiveView = {
  hasFocus: () => document.hasFocus(),
  getActiveTarget: (): NotificationTarget | undefined => {
    const matches = getCurrentMatches();
    const last = matches[matches.length - 1];
    if (!last) return undefined;
    const params = last.params as Record<string, string | undefined>;
    switch (last.routeId) {
      case "/code/tasks/$taskId":
      case "/website/$channelId/tasks/$taskId":
        return params.taskId
          ? { kind: "task", taskId: params.taskId }
          : undefined;
      case "/website/$channelId/dashboards/$dashboardId":
        return params.channelId && params.dashboardId
          ? {
              kind: "canvas",
              channelId: params.channelId,
              dashboardId: params.dashboardId,
            }
          : undefined;
      default:
        return undefined;
    }
  },
};
