import type { NotificationTarget } from "@posthog/platform/notifications";

// Stable identity string for a target. A new kind is a compile error here (the
// switch is exhaustive), so equality and key-based lookups stay in one place.
export function targetKey(target: NotificationTarget): string {
  switch (target.kind) {
    case "task":
      return `task:${target.taskId}`;
    case "canvas":
      return `canvas:${target.channelId}:${target.dashboardId}`;
  }
}

// Whether two targets point at the same thing.
export function targetsEqual(
  a: NotificationTarget | undefined,
  b: NotificationTarget | undefined,
): boolean {
  if (!a || !b) return false;
  return targetKey(a) === targetKey(b);
}

export type NotificationChannel = "suppress" | "toast" | "native";

// The focus-aware routing decision, the heart of the notification bus:
//   - app unfocused (user in another OS app) → native OS notification
//   - app focused, already looking at the target → suppress (they can see it)
//   - app focused, looking elsewhere → in-app toast
//
// Pure so it's exhaustively unit-tested without the DI graph.
export function routeNotification(args: {
  appFocused: boolean;
  viewingTarget: NotificationTarget | undefined;
  notificationTarget: NotificationTarget | undefined;
}): NotificationChannel {
  if (!args.appFocused) return "native";
  if (
    args.notificationTarget &&
    targetsEqual(args.viewingTarget, args.notificationTarget)
  ) {
    return "suppress";
  }
  return "toast";
}
