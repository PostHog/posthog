import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/domain-types";

// Only the transition into terminal closes: mounting already-terminal
// (opened from Archive) is the destination and stays.
export function reportAutoCloseTransition(
  activeReportId: string | null,
  report: SignalReport,
): { nextActiveReportId: string | null; closed: boolean } {
  if (!isDismissedReport(report)) {
    return { nextActiveReportId: report.id, closed: false };
  }
  if (activeReportId !== report.id) {
    return { nextActiveReportId: activeReportId, closed: false };
  }
  return { nextActiveReportId: null, closed: true };
}
