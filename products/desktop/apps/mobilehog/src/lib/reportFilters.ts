import {
  buildArchiveListOrdering,
  buildSignalReportListOrdering,
  INBOX_ACTIONABLE_ACTIONABILITY_FILTER,
  INBOX_ACTIONABLE_REPORT_STATUS_FILTER,
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_PULL_REQUEST_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import { isSafeGitHubPullRequestUrl } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportsQueryParams,
} from "@posthog/shared/domain-types";

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

// The list API matches merged and closed PRs too, so the PR tab keeps only the
// ones still open.
export function hasOpenImplementationPr(report: SignalReport): boolean {
  if (!report.implementation_pr_url || report.implementation_pr_merged) {
    return false;
  }
  const state = report.implementation_pr_state;
  return state !== "merged" && state !== "closed";
}

// The URL comes from task output, so only a real GitHub PR link may reach the
// OS link handler.
export function openPullRequestUrl(report: SignalReport): string | null {
  const url = report.implementation_pr_url;
  return url &&
    hasOpenImplementationPr(report) &&
    isSafeGitHubPullRequestUrl(url)
    ? url
    : null;
}
