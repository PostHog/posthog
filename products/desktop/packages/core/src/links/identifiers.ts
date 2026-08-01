export interface LinkLogger {
  info(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  error(message: string, ...args: unknown[]): void;
  debug(message: string, ...args: unknown[]): void;
}

export const TASK_LINK_SERVICE = Symbol.for("posthog.core.taskLinkService");
export const INBOX_LINK_SERVICE = Symbol.for("posthog.core.inboxLinkService");
export const SCOUT_LINK_SERVICE = Symbol.for("posthog.core.scoutLinkService");
export const NEW_TASK_LINK_SERVICE = Symbol.for(
  "posthog.core.newTaskLinkService",
);
export const APPROVAL_LINK_SERVICE = Symbol.for(
  "posthog.core.approvalLinkService",
);
// Carries notification-click "open this target" intent from main → renderer.
// Unlike the link services above, it registers no OS URL-scheme handler — it
// exists purely so a clicked native notification can navigate to its target.
export const OPEN_TARGET_LINK_SERVICE = Symbol.for(
  "posthog.core.openTargetLinkService",
);
export const CANVAS_LINK_SERVICE = Symbol.for("posthog.core.canvasLinkService");
export const CHANNEL_LINK_SERVICE = Symbol.for(
  "posthog.core.channelLinkService",
);
