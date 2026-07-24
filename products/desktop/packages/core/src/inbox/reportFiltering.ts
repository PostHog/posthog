import type {
  SignalReport,
  SignalReportOrderingField,
  SignalReportPriority,
  SignalReportStatus,
} from "@posthog/shared/types";

/**
 * Comma-separated statuses for the inbox query. We pull `failed` so the Runs
 * tab can surface failed runs in its Recently finished section.
 */
export const INBOX_PIPELINE_STATUS_FILTER =
  "potential,candidate,in_progress,ready,pending_input,failed";

/**
 * Status filter for the Archive tab — the two terminal, not-in-inbox states:
 * `suppressed` (the user archived it; restorable) and `resolved` (its
 * implementation PR merged; terminal, shown for reference only). `deleted` is
 * permanent and stripped server-side; snooze is a temporary `snoozed_until`
 * timestamp, not a status, and auto-returns. See `isDismissedReport` for the
 * full rationale. Both states are excluded from the main pipeline query, so the
 * Archive tab fetches them explicitly.
 */
export const INBOX_DISMISSED_STATUS_FILTER = "suppressed,resolved";

/**
 * Status filter for the Pull requests tab's list and count. Only `ready` PRs —
 * a Responder draft awaiting review — are surfaced; PRs that have already been
 * merged/closed (`resolved`) or are still running drop off so the tab and its
 * count reflect only actionable work the user can act on. Keeps the count
 * honest about what the list actually shows.
 */
export const INBOX_PULL_REQUEST_STATUS_FILTER = "ready";

/** Polling interval for inbox queries while the Electron window is focused. */
export const INBOX_REFETCH_INTERVAL_MS = 3000;

function normalizeReviewerId(value: string): string {
  return value.trim();
}

export function filterReportsBySearch(
  reports: SignalReport[],
  query: string,
): SignalReport[] {
  const trimmed = query.trim();
  if (!trimmed) return reports;

  const lower = trimmed.toLowerCase();
  return reports.filter(
    (report) =>
      report.title?.toLowerCase().includes(lower) ||
      report.summary?.toLowerCase().includes(lower) ||
      report.id.toLowerCase().includes(lower),
  );
}

/**
 * Build a comma-separated status filter string for the API from an array of statuses.
 */
export function buildStatusFilterParam(statuses: SignalReportStatus[]): string {
  return statuses.join(",");
}

/**
 * Comma-separated `ordering` for the signal report list API:
 * 1. Status rank (ready first – semantic server-side rank, always applied)
 * 2. Toolbar-selected field (priority, total_weight, created_at, etc.)
 * 3. A tiebreak so reports the primary field can't separate come back in a
 *    sensible order. Sorting by priority (a coarse 5-bucket P0–P4 rank) tiebreaks
 *    by `-created_at` so the newest report wins within a tier; every other field
 *    tiebreaks by `priority` so the most urgent report wins. The server applies
 *    the clauses in order (and falls back to `id`), so this only breaks ties.
 *
 * Reviewer scope is applied via the `suggested_reviewers` param, not ordering:
 * a `-is_suggested_reviewer` tiebreak would float the user's reports to the top
 * of the first (and only loaded) page, starving the "Entire project" scope.
 */
export function buildSignalReportListOrdering(
  field: SignalReportOrderingField,
  direction: "asc" | "desc",
): string {
  const fieldKey = direction === "desc" ? `-${field}` : field;
  const tiebreak = field === "priority" ? "-created_at" : "priority";
  return ["status", fieldKey, tiebreak].join(",");
}

/**
 * Ordering for the Archive tab, which lists two terminal statuses
 * (`suppressed` + `resolved`). Unlike the pipeline ordering above, it must NOT
 * prefix with `status`: that would group one terminal state ahead of the other
 * before applying the time sort, burying recent completions behind older items
 * from the sibling status. Sort purely by the selected field so the list is
 * globally newest-changed-first across both states.
 */
export function buildArchiveListOrdering(
  field: SignalReportOrderingField,
  direction: "asc" | "desc",
): string {
  return direction === "desc" ? `-${field}` : field;
}

export function buildSuggestedReviewerFilterParam(
  reviewerIds: string[],
): string | undefined {
  const normalizedIds = reviewerIds.map(normalizeReviewerId).filter(Boolean);

  if (normalizedIds.length === 0) {
    return undefined;
  }

  return Array.from(new Set(normalizedIds)).join(",");
}

export function buildPriorityFilterParam(
  priorities: SignalReportPriority[],
): string | undefined {
  if (priorities.length === 0) {
    return undefined;
  }
  return Array.from(new Set(priorities)).join(",");
}
