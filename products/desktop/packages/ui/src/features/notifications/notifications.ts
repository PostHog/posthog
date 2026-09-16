import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
  type NotificationTarget,
} from "@posthog/platform/notifications";
import type { TaskActivityKind } from "@posthog/shared/domain-types";
import { toast } from "@posthog/ui/primitives/toast";
import { openNotificationTarget } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import {
  playbackRateForTaskDuration,
  playCompletionSound,
  resolveSoundUrl,
} from "@posthog/ui/utils/sounds";
import { inject, injectable } from "inversify";
import { summarizeError } from "./errorDetails";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type INotificationSettings,
  NOTIFICATION_SETTINGS_PROVIDER,
} from "./identifiers";
import { describeTarget, routeNotification } from "./routeNotification";

const MAX_TITLE_LENGTH = 50;
const log = logger.scope("notifications");

// Why a notification was raised. Every delivery logs it, so a sound the user
// did not expect can be traced back to the producer that asked for it.
export type NotificationReason =
  | "task_completed"
  | "task_needs_input"
  | "canvas_generation"
  | "image_build"
  | "error"
  | "settings_test";

// In-app toast presentation for the focused-but-elsewhere tier. Only levels that
// support an action link are allowed (the bus derives the action from `target`).
type ToastLevel = "success" | "error" | "warning";

export interface NotificationDescriptor {
  reason: NotificationReason;
  // Extra facts the producer knows about the trigger (which code path raised
  // it, the stop reason, the task run). Logged verbatim beside `reason`.
  debug?: Record<string, unknown>;
  // Native title; defaults to "PostHog".
  title?: string;
  body: string;
  // What the notification is about — drives suppression (am I viewing it?) and
  // click navigation for both the toast and native tiers.
  target?: NotificationTarget;
  toast?: {
    level?: ToastLevel;
    description?: string;
    duration?: number;
  };
  silent?: boolean;
  // How long the task took, in ms. When the user enables sound scaling, this
  // drives the completion sound's playback rate (fast task -> faster/higher).
  soundDurationMs?: number;
  // Raw error payload behind an error-level notification. Never rendered into
  // the toast itself (it doesn't fit); the central toast wrapper adds a "View
  // larger" action that opens the pretty-printed payload in the error dialog.
  error?: unknown;
}

export interface TaskActivitySignal {
  taskId: string;
  taskTitle: string;
  activityKind: Extract<TaskActivityKind, "awaiting_input" | "completed">;
  activityAt: string;
}

// The single channel every app notification flows through. Reads focus + the
// active route, decides suppress / toast / native (see routeNotification), and
// dispatches accordingly. Native delivery + dock effects are gated by the user's
// notification settings; the in-app toast always shows (it's non-intrusive and
// only appears while the app is focused).
@injectable()
export class NotificationBus {
  private readonly taskActivityListeners = new Set<
    (signal: TaskActivitySignal) => void
  >();

  constructor(
    @inject(NOTIFICATIONS_SERVICE)
    private readonly notifications: INotifications,
    @inject(NOTIFICATION_SETTINGS_PROVIDER)
    private readonly settings: INotificationSettings,
    @inject(ACTIVE_VIEW_PROVIDER)
    private readonly view: IActiveView,
  ) {}

  notify(descriptor: NotificationDescriptor): void {
    const appFocused = this.view.hasFocus();
    const viewingTarget = this.view.getActiveTarget();
    const channel = routeNotification({
      appFocused,
      viewingTarget,
      notificationTarget: descriptor.target,
    });

    const settings = this.settings.get();
    const playbackRate =
      settings.scaleSoundWithTaskLength &&
      descriptor.soundDurationMs !== undefined
        ? playbackRateForTaskDuration(descriptor.soundDurationMs)
        : 1;
    // Answers "does a sound come out of this?" for both the log line and the
    // native silent flag below. A `custom:` id whose sound was deleted
    // resolves to nothing. Under a `random-*` sound this re-picks, so it
    // reports whether a sound plays, not which one.
    const willPlaySound =
      resolveSoundUrl(settings.completionSound, settings.customSounds) !== null;
    // A native notification we leave unsilenced rings the OS chime instead, so
    // the line has to name that noise rather than read as silence.
    const nativeSilent = descriptor.silent ?? willPlaySound;
    const osChimePlayed =
      channel === "native" && settings.desktopNotifications && !nativeSilent;

    // One line for every notification, including the suppressed ones. At info
    // level on purpose: packaged builds drop debug, and "the app made a noise
    // and I do not know why" is not reproducible without this in the log file.
    // `body` stays out — info lines reach central logs and it carries task,
    // canvas and image names, which `reason` and `target` identify without.
    log.info("Notification", {
      reason: descriptor.reason,
      channel,
      target: describeTarget(descriptor.target),
      viewingTarget: describeTarget(viewingTarget),
      appFocused,
      sound: settings.completionSound,
      soundPlayed: channel !== "suppress" && willPlaySound,
      osChimePlayed,
      volume: settings.completionVolume,
      playbackRate,
      soundDurationMs: descriptor.soundDurationMs,
      desktopNotifications: settings.desktopNotifications,
      context: descriptor.debug,
    });

    if (channel === "suppress") return;

    // Sound fires on both delivered tiers (toast + native), not on suppress —
    // matching the pre-bus behavior where any non-suppressed notification rang.
    playCompletionSound(
      settings.completionSound,
      settings.completionVolume,
      settings.customSounds,
      playbackRate,
      descriptor.reason,
    );

    if (channel === "toast") {
      this.showToast(descriptor);
      return;
    }

    // native
    if (settings.desktopNotifications) {
      this.notifications.notify({
        title: descriptor.title ?? "PostHog",
        body: descriptor.body,
        silent: nativeSilent,
        target: descriptor.target,
      });
    }
    if (settings.dockBadgeNotifications)
      this.notifications.showUnreadIndicator();
    if (settings.dockBounceNotifications) this.notifications.requestAttention();
  }

  // --- Task-specific producers (delegate to notify) ---

  notifyPromptComplete(
    taskTitle: string,
    stopReason: string,
    taskId?: string,
    durationMs?: number,
    debug?: Record<string, unknown>,
  ): void {
    if (stopReason !== "end_turn") return;
    this.notify({
      reason: "task_completed",
      debug: { ...debug, stopReason },
      body: `"${this.truncateTitle(taskTitle)}" finished`,
      target: taskId ? { kind: "task", taskId } : undefined,
      toast: { level: "success" },
      soundDurationMs: durationMs,
    });
    this.emitTaskActivity(taskId, taskTitle, "completed");
  }

  subscribeToTaskActivity(
    listener: (signal: TaskActivitySignal) => void,
  ): () => void {
    this.taskActivityListeners.add(listener);
    return () => this.taskActivityListeners.delete(listener);
  }

  notifyPermissionRequest(
    taskTitle: string,
    taskId?: string,
    debug?: Record<string, unknown>,
  ): void {
    this.notify({
      reason: "task_needs_input",
      debug,
      body: `"${this.truncateTitle(taskTitle)}" needs your input`,
      target: taskId ? { kind: "task", taskId } : undefined,
      toast: { level: "warning" },
    });
    this.emitTaskActivity(taskId, taskTitle, "awaiting_input");
  }

  // Error entry point: the toast carries a one-line summary; the raw payload
  // rides along on `error` and stays inspectable behind the View larger action.
  notifyError(
    title: string,
    error: unknown,
    target?: NotificationTarget,
  ): void {
    const summary = summarizeError(error);
    this.notify({
      reason: "error",
      title,
      body: summary,
      target,
      toast: { level: "error", description: summary },
      error,
    });
  }

  private showToast(descriptor: NotificationDescriptor): void {
    const level = descriptor.toast?.level ?? "success";
    toast[level](descriptor.title ?? descriptor.body, {
      description: descriptor.toast?.description,
      duration: descriptor.toast?.duration,
      action: this.deriveAction(descriptor),
      error: descriptor.error,
    });
  }

  private deriveAction(
    descriptor: NotificationDescriptor,
  ): { label: string; onClick: () => void } | undefined {
    const target = descriptor.target;
    if (!target) return undefined;
    // Route through the shared open-target handler so the toast click lands on
    // the same place a native notification click would — channel-aware for
    // tasks filed to a channel. Label is the only kind-specific bit.
    const label = target.kind === "task" ? "View task" : "View canvas";
    return { label, onClick: () => openNotificationTarget(target) };
  }

  private truncateTitle(title: string): string {
    if (title.length <= MAX_TITLE_LENGTH) return title;
    return `${title.slice(0, MAX_TITLE_LENGTH)}...`;
  }

  private emitTaskActivity(
    taskId: string | undefined,
    taskTitle: string,
    activityKind: TaskActivitySignal["activityKind"],
  ): void {
    if (!taskId) return;
    const signal: TaskActivitySignal = {
      taskId,
      taskTitle,
      activityKind,
      activityAt: new Date().toISOString(),
    };
    for (const listener of this.taskActivityListeners) {
      try {
        listener(signal);
      } catch (error) {
        log.error("Task activity subscriber failed", { error });
      }
    }
  }
}
