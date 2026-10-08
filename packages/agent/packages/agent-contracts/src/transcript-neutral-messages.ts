/**
 * Whether a line on the ACP wire may close a streamed assistant message.
 *
 * Both directions of the wire are tapped into the session log writer, which
 * groups a run of `agent_message_chunk` updates into one message and closes that
 * group when any other line arrives. Closing a message the model is still
 * streaming splits one answer into two parts, and the Slack relay posts only the
 * last part, so the reply starts mid-sentence at whatever point the stream delta
 * ended. ACP's own `session/…` requests keep their boundary meaning, because a
 * prompt and a permission request do belong in the transcript.
 *
 * A response carries no method, so its own line cannot say what it answers.
 * Tracking the outstanding `_posthog/` control calls is what separates the
 * answer to a session refresh, which must not close anything, from the
 * `session/prompt` response, which is the only turn-done signal a local session
 * gets: the Claude adapter emits `_posthog/turn_complete` from the cloud server
 * alone, so a local turn ends with chunks and that response and nothing else.
 *
 * Hydration reconciliation runs its own tracker over the same lines. If the two
 * disagree, a resumed transcript duplicates part of the answer.
 */

/**
 * An unlisted `_posthog/` notification is neutral, which is the safe side of the
 * trade: a missed boundary joins two messages, a false one loses the first.
 */
const TRANSCRIPT_EVENT_NOTIFICATION_METHODS = new Set([
  "_posthog/background_turn_complete",
  "_posthog/background_turn_started",
  "_posthog/compact_boundary",
  "_posthog/conversation_cleared",
  "_posthog/error",
  "_posthog/initialization_failed",
  "_posthog/permission_request",
  "_posthog/progress",
  "_posthog/task_complete",
  "_posthog/turn_complete",
  "_posthog/user_message",
]);

/** `extNotification` puts the double-prefixed `__posthog/…` form on the wire. */
function canonicalMethod(method: string): string {
  return method.startsWith("__posthog/") ? method.slice(1) : method;
}

export class TranscriptBoundaries {
  /**
   * Ids of `_posthog/` calls still awaiting an answer. Each side of the wire
   * numbers its own requests, so an id can name a control call and a prompt at
   * the same time; a request that is not a control call therefore drops the id
   * it reuses, and an answered call consumes its own.
   */
  private neutralCallIds = new Set<unknown>();

  isNeutral(message: { id?: unknown; method?: unknown }): boolean {
    const isCall = message.id !== undefined;
    if (typeof message.method !== "string") {
      return isCall && this.neutralCallIds.delete(message.id);
    }
    const method = canonicalMethod(message.method);
    const isPosthogMethod = method.startsWith("_posthog/");
    if (isCall) {
      if (isPosthogMethod) {
        this.neutralCallIds.add(message.id);
      } else {
        this.neutralCallIds.delete(message.id);
      }
      return isPosthogMethod;
    }
    return (
      isPosthogMethod && !TRANSCRIPT_EVENT_NOTIFICATION_METHODS.has(method)
    );
  }
}
