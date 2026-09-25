import type { SignalReport } from "@posthog/shared/types";

/**
 * The Desktop reports inbox follows web's actionable report grouping. Both
 * boundaries are server-countable: Review and merge is the `monitoring` view,
 * Needs decision is the `needs_decision` view.
 */
export interface InboxReportSections {
  /** Ready reports with an implementation PR waiting for review. */
  reviewAndMerge: SignalReport[];
  /** The Needs decision queue: see `isNeedsDecisionReport`. */
  needsPr: SignalReport[];
}

function hasImplementationPr(report: SignalReport): boolean {
  return !!report.implementation_pr_url?.trim();
}

function isActionable(report: SignalReport): boolean {
  return (
    report.actionability === "immediately_actionable" ||
    report.actionability === "requires_human_input"
  );
}

/**
 * Needs decision membership, mirroring the server's `needs_decision` view.
 * A failed report qualifies on its status alone: the run stopped before it
 * could produce an actionability judgment, so a person must decide what
 * happens to it. Failed reports also stay in Runs, which keeps the run
 * context, but the queue is where they get reviewed.
 */
export function isNeedsDecisionReport(report: SignalReport): boolean {
  if (report.status === "failed") return true;
  return (
    !hasImplementationPr(report) &&
    isActionable(report) &&
    (report.status === "ready" || report.status === "pending_input")
  );
}

/** Partition the list, preserving its order. */
export function partitionInboxReports(
  reports: SignalReport[],
): InboxReportSections {
  const reviewAndMerge: SignalReport[] = [];
  const needsPr: SignalReport[] = [];
  for (const report of reports) {
    if (report.status === "ready" && hasImplementationPr(report)) {
      reviewAndMerge.push(report);
    } else if (isNeedsDecisionReport(report)) {
      needsPr.push(report);
    }
  }
  return { reviewAndMerge, needsPr };
}
