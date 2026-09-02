import type { SignalReport } from "@posthog/shared/types";

/**
 * The Desktop reports inbox follows web's actionable report grouping. Both
 * boundaries are server-countable: report status plus whether an
 * implementation PR exists.
 */
export interface InboxReportSections {
  /** Ready reports with an implementation PR waiting for review. */
  reviewAndMerge: SignalReport[];
  /** Actionable ready/pending-input reports without an implementation PR. */
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
 * Partition the already actionability-filtered list, preserving its order.
 * Pipeline and failed reports stay in Runs instead of appearing as a third
 * report section.
 */
export function partitionInboxReports(
  reports: SignalReport[],
): InboxReportSections {
  const reviewAndMerge: SignalReport[] = [];
  const needsPr: SignalReport[] = [];
  for (const report of reports) {
    const hasPr = hasImplementationPr(report);
    if (report.status === "ready" && hasPr) {
      reviewAndMerge.push(report);
    } else if (
      !hasPr &&
      isActionable(report) &&
      (report.status === "ready" || report.status === "pending_input")
    ) {
      needsPr.push(report);
    }
  }
  return { reviewAndMerge, needsPr };
}
