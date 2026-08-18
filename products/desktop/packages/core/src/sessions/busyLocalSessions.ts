import type { AgentSession } from "@posthog/shared";

/**
 * Sessions an app restart would actually interrupt: local agents with a turn
 * in flight. Cloud runs execute on PostHog's infrastructure and reattach after
 * a relaunch, and an idle local session resumes from its persisted transcript,
 * so neither counts.
 */
export function countBusyLocalSessions(
  sessions: Record<string, AgentSession>,
): number {
  let count = 0;
  for (const session of Object.values(sessions)) {
    if (
      !session.isCloud &&
      session.status === "connected" &&
      session.isPromptPending
    ) {
      count += 1;
    }
  }
  return count;
}
