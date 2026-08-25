import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
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

/** The implementation PR to link to, or null. A merged PR is history, not live work. */
function liveImplementationPrUrl(report: SignalReport): string | null {
  if (report.implementation_pr_merged) return null;
  return report.implementation_pr_url ?? null;
}

/**
 * The one action the verdict banner offers: open the live PR, start the fix, or
 * nothing. Mobile has no continuable-task lookup, so an existing PR is read from
 * `implementation_pr_url` alone.
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
