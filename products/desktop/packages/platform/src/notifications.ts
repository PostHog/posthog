// What a notification is about, for both relevance ("is the user already looking
// at this?") and click navigation (deep-link to it). Lives here, beside the
// capability it describes, because @posthog/platform must not import internal
// packages — so core, host-router, and ui all import the type from here.
export type NotificationTarget =
  | { kind: "task"; taskId: string; taskRunId?: string }
  | { kind: "canvas"; channelId: string; dashboardId: string };

export interface NotificationOptions {
  title: string;
  body: string;
  silent: boolean;
  target?: NotificationTarget;
}

export interface INotifications {
  notify(options: NotificationOptions): void;
  showUnreadIndicator(): void;
  requestAttention(): void;
}

export const NOTIFICATIONS_SERVICE = Symbol.for(
  "posthog.platform.notifications",
);
