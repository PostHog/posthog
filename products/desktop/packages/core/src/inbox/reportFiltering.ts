import type {
  SignalReport,
  SignalReportOrderingField,
  SignalReportPriority,
  SignalReportRankingOrderingField,
  SignalReportStatus,
  SignalReportsQueryParams,
} from "@posthog/shared/types";

export const INBOX_PIPELINE_STATUSES = [
  "ready",
  "pending_input",
  "in_progress",
  "failed",
  "candidate",
  "potential",
] as const satisfies readonly SignalReportStatus[];

/**
 * Comma-separated statuses for the inbox query. We pull `failed` so the Runs
 * tab can surface failed runs in its Recently finished section.
 */
export const INBOX_PIPELINE_STATUS_FILTER = INBOX_PIPELINE_STATUSES.join(",");

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

/**
 * Status filter for the reports inbox page (and its badges). Excludes
 * `potential`: embryonic reports the pipeline hasn't promoted yet, which no
 * surface has ever displayed — fetching them bloats Monitoring with rows
 * nobody can act on and spends the page's row budget on noise. The legacy
 * inbox keeps the broader filter for its Runs accounting.
 */
export const REPORTS_INBOX_STATUS_FILTER = INBOX_PIPELINE_STATUSES.filter(
  (status) => status !== "potential",
).join(",");

/** Web Inbox's actionable report set: ready reports plus ones waiting on human input. */
export const INBOX_ACTIONABLE_REPORT_STATUS_FILTER = "ready,pending_input";

/** The two judgments that web Inbox includes in Review and merge / Needs a PR. */
export const INBOX_ACTIONABLE_ACTIONABILITY_FILTER =
  "immediately_actionable,requires_human_input";

/**
 * Status filter for the Reports tab's count. `isReportTabReport` keeps a report
 * only when it is `ready` and carries no PR, because every other pipeline status
 * is either a queued/live run that belongs to the Runs tab or a `failed` run
 * that is filtered out. Pairing this with `has_implementation_pr: false`
 * reproduces that predicate server-side, so the badge can be counted rather than
 * derived from the loaded pages.
 */
export const INBOX_REPORTS_TAB_STATUS_FILTER = "ready";

/** Polling interval for mobile inbox queries. */
export const INBOX_REFETCH_INTERVAL_MS = 3_000;

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
  // A model sort ranks across statuses, so the score leads, as on web. Status
  // first would let a low score in an earlier status fill the first page.
  if (isRankingSortField(field)) {
    return [fieldKey, "status", "-updated_at"].join(",");
  }
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

const PRIORITY_RANK: Record<SignalReportPriority, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

function reportPriorityRank(report: SignalReport): number {
  return report.priority ? PRIORITY_RANK[report.priority] : 5;
}

/** The sorts the inbox offers: the basic fields plus the staff-only model sorts. */
export type InboxSortField =
  | Extract<
      SignalReportOrderingField,
      "priority" | "created_at" | "total_weight"
    >
  | SignalReportRankingOrderingField;

export type InboxSortDirection = "asc" | "desc";

/** The outcome head each model sort reads from `report.ranking.scores`. */
const RANKING_SORT_HEADS: Record<SignalReportRankingOrderingField, string> = {
  ranking_pr_merged: "pr_merged",
  ranking_pr_created: "pr_created",
  ranking_action: "action",
  ranking_open: "open",
};

/** Staff-only sorts by the ranking model's served probability for one outcome head. Descending only. */
export const INBOX_MODEL_SORT_OPTIONS: readonly {
  label: string;
  field: SignalReportRankingOrderingField;
  direction: InboxSortDirection;
}[] = [
  {
    label: "Most likely to merge",
    field: "ranking_pr_merged",
    direction: "desc",
  },
  {
    label: "Most likely to get a PR",
    field: "ranking_pr_created",
    direction: "desc",
  },
  {
    label: "Most likely to need action",
    field: "ranking_action",
    direction: "desc",
  },
  {
    label: "Most likely to be opened",
    field: "ranking_open",
    direction: "desc",
  },
];

export function isRankingSortField(
  field: string,
): field is SignalReportRankingOrderingField {
  return Object.hasOwn(RANKING_SORT_HEADS, field);
}

/** The served probability a model sort orders by, or null when the report has no score for that head. */
export function rankingSortScore(
  report: SignalReport,
  field: SignalReportRankingOrderingField,
): number | null {
  const score = report.ranking?.scores[RANKING_SORT_HEADS[field]];
  return typeof score === "number" ? score : null;
}

/**
 * The sort the list requests. A model sort persisted while it was available
 * falls back once it is not, because the API rejects it for non-staff users.
 */
export function resolveInboxSort(
  sort: { field: InboxSortField; direction: InboxSortDirection },
  modelSortAvailable: boolean,
  fallback: { field: InboxSortField; direction: InboxSortDirection },
): { field: InboxSortField; direction: InboxSortDirection } {
  return isRankingSortField(sort.field) && !modelSortAvailable
    ? fallback
    : sort;
}

export type InboxCreatedWindow = "24h" | "3d" | "7d" | "14d";

export const INBOX_CREATED_WINDOW_OPTIONS: readonly {
  value: InboxCreatedWindow;
  label: string;
  hours: number;
}[] = [
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "3d", label: "Last 3 days", hours: 3 * 24 },
  { value: "7d", label: "Last 7 days", hours: 7 * 24 },
  { value: "14d", label: "Last 14 days", hours: 14 * 24 },
];

/** The ranking sweep only scores reports from the last 7 days, so a model sort picks this window when none is set. */
const MODEL_SORT_DEFAULT_WINDOW: InboxCreatedWindow = "7d";

/** The window to store after a sort change: a model sort sets the default window when none is set. */
export function createdWindowAfterSort(
  field: InboxSortField,
  createdWindow: InboxCreatedWindow | null,
  timeWindowAvailable: boolean,
): InboxCreatedWindow | null {
  return isRankingSortField(field) &&
    timeWindowAvailable &&
    createdWindow === null
    ? MODEL_SORT_DEFAULT_WINDOW
    : createdWindow;
}

/** The `created_after` bound for a window. Compute it at request time, so a long-open list never sends a stale bound. */
export function createdAfterForWindow(
  window: InboxCreatedWindow | null | undefined,
  now: number = Date.now(),
): string | undefined {
  const option = INBOX_CREATED_WINDOW_OPTIONS.find((o) => o.value === window);
  return option
    ? new Date(now - option.hours * 60 * 60 * 1000).toISOString()
    : undefined;
}

/**
 * List params as a query key holds them. The window stays a preset key, so the
 * key does not change every second. `toSignalReportsRequest` turns it into a
 * `created_after` bound when the request goes out.
 */
export type InboxReportsQueryParams = SignalReportsQueryParams & {
  created_window?: InboxCreatedWindow;
};

export function toSignalReportsRequest({
  created_window,
  ...params
}: InboxReportsQueryParams): SignalReportsQueryParams {
  const createdAfter = createdAfterForWindow(created_window);
  return createdAfter ? { ...params, created_after: createdAfter } : params;
}

// The API puts unscored reports after every scored report, in both directions.
function compareRankingScores(
  left: number | null,
  right: number | null,
  directionMultiplier: number,
): number {
  if (left === null || right === null) {
    return left === right ? 0 : left === null ? 1 : -1;
  }
  return (left - right) * directionMultiplier;
}

export function sortInboxReports(
  reports: SignalReport[],
  field: InboxSortField,
  direction: InboxSortDirection,
): SignalReport[] {
  const directionMultiplier = direction === "asc" ? 1 : -1;
  return [...reports].sort((left, right) => {
    let primary = 0;
    if (isRankingSortField(field)) {
      const ranking = compareRankingScores(
        rankingSortScore(left, field),
        rankingSortScore(right, field),
        directionMultiplier,
      );
      if (ranking !== 0) return ranking;
    } else if (field === "priority") {
      primary = reportPriorityRank(left) - reportPriorityRank(right);
    } else if (field === "total_weight") {
      primary = left.total_weight - right.total_weight;
    } else {
      primary = left.created_at.localeCompare(right.created_at);
    }
    if (primary !== 0) return primary * directionMultiplier;

    const tiebreak =
      field === "priority"
        ? right.created_at.localeCompare(left.created_at)
        : reportPriorityRank(left) - reportPriorityRank(right);
    return tiebreak || left.id.localeCompare(right.id);
  });
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
