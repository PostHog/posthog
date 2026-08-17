import {
  isAgentRunReport,
  isDismissedReport,
  isPullRequestReport,
} from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";

export type ReportSessionSection = "reports" | "runs" | "pulls" | "archive";

export function reportSessionSection(
  report: SignalReport,
): ReportSessionSection {
  if (isDismissedReport(report)) return "archive";
  if (isPullRequestReport(report)) return "pulls";
  if (isAgentRunReport(report) || report.status === "failed") return "runs";
  return "reports";
}

export function partitionReportSessions(
  reports: SignalReport[],
): Record<ReportSessionSection, SignalReport[]> {
  const sections: Record<ReportSessionSection, SignalReport[]> = {
    reports: [],
    runs: [],
    pulls: [],
    archive: [],
  };
  for (const report of reports)
    sections[reportSessionSection(report)].push(report);
  return sections;
}
