import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";

/**
 * The Self-Driving home groups every live report by what it asks of the
 * reader, replacing the inbox's pipeline tabs (Pull requests / Reports /
 * Runs) with one decision-ordered list:
 *
 * - `decision`: the report is waiting on a person — ready and actionable,
 *   waiting on input, or failed and needing a call.
 * - `review`: implementation is in flight; there is a PR to review.
 * - `in-progress`: the agent is still investigating; nothing to do yet.
 * - `fyi`: read-and-archive — not actionable, or likely already fixed.
 *
 * Terminal reports (archived, resolved, deleted) are excluded; they live
 * behind the archive filter.
 */
export type ReportTriageGroup = "decision" | "review" | "in-progress" | "fyi";

export function reportTriageGroup(
  report: SignalReport,
): ReportTriageGroup | null {
  switch (report.status) {
    case "suppressed":
    case "resolved":
    case "deleted":
      return null;
    case "pending_input":
    case "failed":
      return "decision";
    case "potential":
    case "candidate":
    case "in_progress":
      return report.implementation_pr_url ? "review" : "in-progress";
    case "ready":
      break;
  }
  if (report.implementation_pr_url) return "review";
  if (report.already_addressed || report.actionability === "not_actionable") {
    return "fyi";
  }
  return "decision";
}

export interface TriagedReports {
  decision: SignalReport[];
  review: SignalReport[];
  inProgress: SignalReport[];
  fyi: SignalReport[];
}

const PRIORITY_RANK: Record<SignalReportPriority, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

function triageOrder(a: SignalReport, b: SignalReport): number {
  const aRank = a.priority
    ? PRIORITY_RANK[a.priority]
    : Number.MAX_SAFE_INTEGER;
  const bRank = b.priority
    ? PRIORITY_RANK[b.priority]
    : Number.MAX_SAFE_INTEGER;
  if (aRank !== bRank) return aRank - bRank;
  const aTs = a.updated_at ?? a.created_at ?? "";
  const bTs = b.updated_at ?? b.created_at ?? "";
  return bTs.localeCompare(aTs);
}

/**
 * Bucket and order the reports the Self-Driving home renders. Within each
 * group: priority first (P0 outranks P4, unprioritized last), then newest
 * activity — so the top of the page is the most important undecided thing,
 * not the most recent one.
 */
export function groupReportsForTriage(reports: SignalReport[]): TriagedReports {
  const grouped: TriagedReports = {
    decision: [],
    review: [],
    inProgress: [],
    fyi: [],
  };
  for (const report of reports) {
    switch (reportTriageGroup(report)) {
      case "decision":
        grouped.decision.push(report);
        break;
      case "review":
        grouped.review.push(report);
        break;
      case "in-progress":
        grouped.inProgress.push(report);
        break;
      case "fyi":
        grouped.fyi.push(report);
        break;
      case null:
        break;
    }
  }
  grouped.decision.sort(triageOrder);
  grouped.review.sort(triageOrder);
  grouped.inProgress.sort(triageOrder);
  grouped.fyi.sort(triageOrder);
  return grouped;
}
