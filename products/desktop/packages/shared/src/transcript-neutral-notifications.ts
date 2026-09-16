/**
 * Notifications the agent server emits about itself rather than about the
 * conversation. They arrive at arbitrary moments, including between two
 * chunks of a message the model is still streaming, so no consumer that
 * groups chunks into messages may treat one as a message boundary. The
 * session log writer and hydration reconciliation share this predicate;
 * if they disagree, a resumed transcript duplicates part of the answer.
 *
 * `_posthog/progress` is deliberately absent: the client renders it as a
 * card in the transcript, so it is a visible boundary.
 */
const TRANSCRIPT_NEUTRAL_NOTIFICATION_METHODS = [
  "_posthog/console",
  "_posthog/mode_change",
  "_posthog/status",
  "_posthog/task_notification",
  "_posthog/usage_update",
  "_posthog/resources_used",
  "_posthog/rtk_savings",
  "_posthog/codex_goal",
];

/** Accepts the double-prefixed `__posthog/…` form extNotification puts on the wire. */
export function isTranscriptNeutralNotificationMethod(
  method: string | undefined,
): boolean {
  if (!method) return false;
  return TRANSCRIPT_NEUTRAL_NOTIFICATION_METHODS.some(
    (neutral) => method === neutral || method === `_${neutral}`,
  );
}
