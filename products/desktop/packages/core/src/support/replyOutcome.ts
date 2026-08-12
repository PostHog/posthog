import { requestErrorStatus } from "@posthog/api-client/fetcher";
import {
  SUPPORT_REPLY_REPLAY_WINDOW_MS,
  type SupportTicketMessage,
} from "@posthog/api-client/posthog-client";

/**
 * Whether a failed reply might still have reached the server.
 *
 * `null` means it definitely did not: the request was rejected before anything
 * was written, so the draft is safe to keep and send again. Throttling lands
 * here — the limiter rejects ahead of the handler. Every other value means the
 * outcome is unknown and the thread has to be checked before telling the person
 * anything, because a reply that did land would be sent to the customer twice.
 */
export type UnconfirmedReplyReason =
  | "network"
  | "timeout"
  | "in-progress"
  | "server-error"
  | null;

export function classifyReplyFailure(error: unknown): UnconfirmedReplyReason {
  const status = requestErrorStatus(error);

  if (status === undefined) {
    return "network";
  }
  if (status === 408) {
    return "timeout";
  }
  if (status === 409) {
    return "in-progress";
  }
  if (status >= 500) {
    return "server-error";
  }
  return null;
}

/**
 * Find a reply in the thread that matches the one whose send failed, so an
 * unknown outcome can be resolved without asking the person to guess.
 *
 * Matching stays deliberately narrow: same body, same privacy, authored by the
 * team, and created inside the server's replay window measured from when the
 * attempt started. Without an author identity to compare, a teammate's
 * identical reply would be indistinguishable from ours, so callers that cannot
 * scope the thread to one author should treat a match as unresolved.
 */
export function findSentReply(
  messages: readonly SupportTicketMessage[],
  attempt: { message: string; isPrivate: boolean; startedAt: number },
): SupportTicketMessage | null {
  const earliestAcceptable = attempt.startedAt - SUPPORT_REPLY_REPLAY_WINDOW_MS;

  for (const message of messages) {
    const createdAt = Date.parse(message.created_at);
    if (Number.isNaN(createdAt) || createdAt < earliestAcceptable) {
      continue;
    }
    if (
      message.content === attempt.message &&
      message.is_private === attempt.isPrivate &&
      message.author_type === "support"
    ) {
      return message;
    }
  }

  return null;
}
