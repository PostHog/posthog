import type { SessionService } from "@posthog/core/sessions/sessionService";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { fireSideQuestion } from "@posthog/ui/features/sessions/sideQuestionStore";
import { track } from "@posthog/ui/shell/analytics";

export const SESSION_SUMMARY_LABEL = "Session summary";

const SESSION_SUMMARY_PROMPT = `Create a concise handoff summary for another coding agent. Include the user's goal, constraints, decisions, current progress, relevant files, commands and tests, remaining work, and blockers. Do not continue the task. Return only the handoff summary.`;

/**
 * Asks the running agent to write a carry-over summary for another agent. The
 * exchange runs beside the conversation and lands in the session summary
 * panel. False when one is already on its way.
 */
export function startSessionSummary(
  sessionService: Pick<SessionService, "askSideQuestion">,
  taskId: string,
  taskRunId: string,
  source: "retry" | "task_menu" = "task_menu",
): boolean {
  track(ANALYTICS_EVENTS.SESSION_SUMMARY_REQUESTED, {
    task_id: taskId,
    source,
  });
  return fireSideQuestion(
    sessionService,
    taskId,
    taskRunId,
    SESSION_SUMMARY_PROMPT,
    { kind: "summary", label: SESSION_SUMMARY_LABEL },
  );
}
