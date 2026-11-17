import type { SignalReport, SignalReportPrState } from "./domain-types";
import type { SignalReportStatus } from "./signal-types";

export type ReportRunVariant = "queued" | "live" | "completed" | "failed";

interface ReportStatusBehavior {
  canResolve: boolean;
  isTerminal: boolean;
  runVariant: ReportRunVariant;
}

// Resolve eligibility follows SignalReport.transition_to in products/signals/backend/models.py.
export const REPORT_STATUS_BEHAVIOR = {
  potential: { canResolve: false, isTerminal: false, runVariant: "queued" },
  candidate: { canResolve: false, isTerminal: false, runVariant: "queued" },
  in_progress: { canResolve: false, isTerminal: false, runVariant: "live" },
  pending_input: { canResolve: true, isTerminal: false, runVariant: "live" },
  ready: { canResolve: true, isTerminal: false, runVariant: "completed" },
  failed: { canResolve: true, isTerminal: false, runVariant: "failed" },
  monitoring: { canResolve: true, isTerminal: true, runVariant: "completed" },
  closed: { canResolve: true, isTerminal: true, runVariant: "completed" },
  resolved: { canResolve: false, isTerminal: true, runVariant: "completed" },
  suppressed: { canResolve: false, isTerminal: true, runVariant: "completed" },
  deleted: { canResolve: false, isTerminal: true, runVariant: "completed" },
} as const satisfies Record<SignalReportStatus, ReportStatusBehavior>;

export function canResolveReport(
  report: Pick<SignalReport, "status">,
): boolean {
  return REPORT_STATUS_BEHAVIOR[report.status].canResolve;
}

export function isTerminalReport(
  report: Pick<SignalReport, "status">,
): boolean {
  return REPORT_STATUS_BEHAVIOR[report.status].isTerminal;
}

export function resolveReportRunVariant(
  status: SignalReportStatus,
): ReportRunVariant {
  return REPORT_STATUS_BEHAVIOR[status].runVariant;
}

export function hasOpenImplementationPr(
  report: Pick<
    SignalReport,
    | "implementation_pr_url"
    | "implementation_pr_state"
    | "implementation_pr_merged"
  > & {
    pull_requests?: readonly {
      url: string;
      state: SignalReportPrState;
      merged: boolean;
    }[];
  },
): boolean {
  if (report.pull_requests !== undefined) {
    return report.pull_requests.some(
      (pr) =>
        !!pr.url &&
        !pr.merged &&
        pr.state !== "closed" &&
        pr.state !== "merged",
    );
  }
  return (
    !!report.implementation_pr_url &&
    !report.implementation_pr_merged &&
    report.implementation_pr_state !== "closed" &&
    report.implementation_pr_state !== "merged"
  );
}
