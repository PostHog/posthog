import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  hasActiveReportPullRequest,
  primaryReportPullRequest,
} from "@posthog/core/inbox/reportPullRequests";
import type { SignalReport } from "@posthog/shared/domain-types";

export type ReportVerdictAction =
  | { kind: "start"; label: string; awaitingInput: boolean }
  | { kind: "view_pr"; url: string }
  | null;

/** True when the report is blocked on user input the reader can supply. */
export function isReportAwaitingInput(report: SignalReport): boolean {
  return (
    report.status === "pending_input" ||
    (report.status === "ready" &&
      report.actionability === "requires_human_input")
  );
}

/**
 * Only active, valid GitHub links can offer the review action.
 */
function liveImplementationPrUrl(report: SignalReport): string | null {
  if (!hasActiveReportPullRequest(report)) return null;
  const url = primaryReportPullRequest(report).url;
  if (!url || !parsePrUrl(url)) return null;
  return url;
}

/**
 * The one action the verdict banner offers: open the live PR, start the fix, or
 * nothing.
 */
export function resolveReportVerdictAction(
  report: SignalReport,
): ReportVerdictAction {
  if (
    report.status === "resolved" ||
    report.status === "suppressed" ||
    report.status === "deleted"
  ) {
    return null;
  }
  const prUrl = liveImplementationPrUrl(report);
  if (prUrl) return { kind: "view_pr", url: prUrl };
  if (canCreateImplementationPr(report)) {
    const awaitingInput = isReportAwaitingInput(report);
    return {
      kind: "start",
      label: awaitingInput ? "Implement as new task" : "Start task",
      awaitingInput,
    };
  }
  return null;
}
