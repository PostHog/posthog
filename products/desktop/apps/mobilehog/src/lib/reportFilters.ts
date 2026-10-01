import {
  buildArchiveListOrdering,
  buildSignalReportListOrdering,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_PULL_REQUEST_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import type { SignalReportsQueryParams } from "@posthog/shared/domain-types";

export type ReportFilter = "attention" | "pull-requests" | "dismissed";

export const REPORT_FILTERS: { value: ReportFilter; label: string }[] = [
  { value: "attention", label: "Needs attention" },
  { value: "pull-requests", label: "PR ready" },
  { value: "dismissed", label: "Dismissed" },
];

export function reportFilterParams(
  filter: ReportFilter,
): SignalReportsQueryParams {
  switch (filter) {
    case "attention":
      return {
        status: INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
        actionability: INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
        ordering: buildSignalReportListOrdering("priority", "desc"),
      };
    case "pull-requests":
      return {
        status: INBOX_PULL_REQUEST_STATUS_FILTER,
        has_implementation_pr: true,
        ordering: buildSignalReportListOrdering("priority", "desc"),
      };
    case "dismissed":
      return {
        status: INBOX_DISMISSED_STATUS_FILTER,
        ordering: buildArchiveListOrdering("updated_at", "desc"),
      };
  }
}
