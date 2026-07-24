import type { SignalReport } from "@posthog/shared/types";

/**
 * Statuses that are out of the inbox entirely (user-suppressed, resolved, or
 * removed). `resolved` is terminal — its implementation PR merged — so it drops
 * out of the live inbox and is surfaced only in the Archive tab for reference.
 * `failed` is NOT in here: failed runs surface in the Runs tab's Recently
 * finished section so the user can see what went wrong. Other tabs filter
 * them out via their own predicates.
 */
export const INBOX_EXCLUDED_STATUSES = new Set<SignalReport["status"]>([
  "suppressed",
  "resolved",
  "deleted",
]);

export function isExcludedFromInbox(report: SignalReport): boolean {
  return INBOX_EXCLUDED_STATUSES.has(report.status);
}

/**
 * Archive tab membership — the two terminal, not-in-inbox states. `suppressed`
 * is "the user archived this out of the inbox" (the archive action sets it; it
 * is restorable). `resolved` is "the implementation PR merged" — terminal, set
 * server-side, shown for reference only and not restorable. The other
 * not-in-inbox states are deliberately excluded: `deleted` is permanent (gone,
 * never restorable, stripped server-side), and snooze is not a status at all —
 * it is a temporary `snoozed_until` timestamp on an otherwise-active report that
 * auto-returns to the inbox when it elapses, so it doesn't belong in a manual
 * restore list. Archived reports are fetched by a dedicated query (the main
 * pipeline query excludes them), so this predicate is applied to that separate
 * list.
 */
export function isDismissedReport(report: SignalReport): boolean {
  return report.status === "suppressed" || report.status === "resolved";
}

export type InboxScope = "for-you" | "entire-project" | `teammate:${string}`;

export const INBOX_SCOPE_FOR_YOU: InboxScope = "for-you";
export const INBOX_SCOPE_ENTIRE_PROJECT: InboxScope = "entire-project";

export function teammateInboxScope(uuid: string): InboxScope {
  return `teammate:${uuid}`;
}

export function parseTeammateInboxScope(scope: InboxScope): string | null {
  if (!scope.startsWith("teammate:")) return null;
  const uuid = scope.slice("teammate:".length).trim();
  return uuid || null;
}

export function isTeammateInboxScope(
  scope: InboxScope,
): scope is `teammate:${string}` {
  return parseTeammateInboxScope(scope) != null;
}

export function inboxScopeTriggerLabel(
  scope: InboxScope,
  teammateName?: string | null,
): string {
  if (scope === INBOX_SCOPE_FOR_YOU) return "For you";
  if (scope === INBOX_SCOPE_ENTIRE_PROJECT) return "Entire project";
  return teammateName?.trim() || "Teammate";
}

export function matchesInboxScope(
  report: SignalReport,
  scope: InboxScope,
): boolean {
  if (isExcludedFromInbox(report)) return false;
  if (scope === INBOX_SCOPE_ENTIRE_PROJECT) return true;
  if (isTeammateInboxScope(scope)) return true;
  return report.is_suggested_reviewer === true;
}

export function countInboxScopeReports(
  reports: SignalReport[],
  scope: InboxScope,
): number {
  return reports.filter((report) => matchesInboxScope(report, scope)).length;
}

export type InboxTabKey = "pulls" | "reports" | "runs" | "dismissed";

export const INBOX_TAB_KEYS: InboxTabKey[] = [
  "pulls",
  "reports",
  "runs",
  "dismissed",
];

export const INBOX_TAB_LABEL: Record<InboxTabKey, string> = {
  pulls: "Pull requests",
  reports: "Reports",
  runs: "Runs",
  dismissed: "Archive",
};

/**
 * Canonical inbox tab list routes. Use these constants instead of hard-coding
 * `/code/inbox/pulls` etc., so renames stay in one place.
 *
 * Detail routes (`/code/inbox/<tab>/$reportId`) stay as TanStack Router
 * literals at call sites – TanStack's typed-link API needs them as literal
 * strings to infer params.
 */
export const INBOX_TAB_LIST_ROUTE: Record<
  InboxTabKey,
  `/code/inbox/${InboxTabKey}`
> = {
  pulls: "/code/inbox/pulls",
  reports: "/code/inbox/reports",
  runs: "/code/inbox/runs",
  dismissed: "/code/inbox/dismissed",
};

const INBOX_DETAIL_PATH_RE = new RegExp(
  `^/code/inbox/(${INBOX_TAB_KEYS.join("|")})/[^/]+$`,
);

export function isInboxDetailPath(pathname: string): boolean {
  return INBOX_DETAIL_PATH_RE.test(pathname);
}

/**
 * PR tab membership: Responder shipped a draft PR and it is `ready` for review.
 * PRs that have already been merged/closed (`resolved`) or are still running
 * are excluded so the tab — and its count — only show actionable PRs, matching
 * the PostHog Cloud inbox.
 */
export function isPullRequestReport(report: SignalReport): boolean {
  return report.status === "ready" && !!report.implementation_pr_url;
}

// ── Runs-tab partitioning ─────────────────────────────────────────────────
// The Runs tab is task-centric: it shows reports whose run is queued, live, or
// recently finished. Each section uses a different predicate; `isAgentRunReport`
// stays as the umbrella for "this report's run is in motion or just finished"
// so other tabs can keep excluding the same set.

const QUEUED_RUN_STATUSES = new Set<SignalReport["status"]>([
  "potential",
  "candidate",
]);

const LIVE_RUN_STATUSES = new Set<SignalReport["status"]>([
  "in_progress",
  "pending_input",
]);

const FINISHED_RUN_STATUSES = new Set<SignalReport["status"]>([
  "ready",
  "failed",
]);

export function isQueuedRunReport(report: SignalReport): boolean {
  return QUEUED_RUN_STATUSES.has(report.status);
}

export function isLiveRunReport(report: SignalReport): boolean {
  return LIVE_RUN_STATUSES.has(report.status);
}

export function isFinishedRunReport(report: SignalReport): boolean {
  return FINISHED_RUN_STATUSES.has(report.status);
}

/**
 * Used by the Runs tab count chip + cross-tab exclusion: only "in motion"
 * runs (queued or live). Finished runs surface inside the Runs tab as recent
 * history but don't inflate the count badge.
 */
export function isAgentRunReport(report: SignalReport): boolean {
  return isQueuedRunReport(report) || isLiveRunReport(report);
}

function runReportTimestampMs(report: SignalReport): number {
  const value = report.updated_at ?? report.created_at;
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

export interface RunsTabSections {
  queued: SignalReport[];
  live: SignalReport[];
  finished: SignalReport[];
}

/**
 * Partition reports into the Runs tab's three rendered sections, each sorted
 * newest-first. The single source of truth shared by `RunsTab` (section
 * rendering) and the open tracker (so `INBOX_REPORT_OPENED.rank` is measured
 * against the row order the user actually saw, not raw query order).
 */
export function partitionRunsTabReports(
  reports: SignalReport[],
): RunsTabSections {
  const queued: SignalReport[] = [];
  const live: SignalReport[] = [];
  const finished: SignalReport[] = [];
  for (const report of reports) {
    if (isQueuedRunReport(report)) queued.push(report);
    else if (isLiveRunReport(report)) live.push(report);
    else if (isFinishedRunReport(report)) finished.push(report);
  }
  const newestFirst = (a: SignalReport, b: SignalReport) =>
    runReportTimestampMs(b) - runReportTimestampMs(a);
  queued.sort(newestFirst);
  live.sort(newestFirst);
  finished.sort(newestFirst);
  return { queued, live, finished };
}

/**
 * Flat Runs-tab order — Queued, then Live, then Recently finished — matching the
 * top-to-bottom order of the rendered sections.
 */
export function orderedRunsTabReports(reports: SignalReport[]): SignalReport[] {
  const { queued, live, finished } = partitionRunsTabReports(reports);
  return [...queued, ...live, ...finished];
}

export function isReportTabReport(report: SignalReport): boolean {
  if (isExcludedFromInbox(report)) return false;
  if (report.status === "failed") return false; // failed runs live in the Runs tab only
  // Any report carrying a PR belongs to the Pull requests tab, even once it has
  // been merged/closed (`resolved`) — those just drop out of the inbox here
  // rather than reappearing as a Report.
  if (report.implementation_pr_url) return false;
  if (isAgentRunReport(report)) return false;
  return true;
}

export function matchesReviewerScope(
  report: SignalReport,
  scope: InboxScope,
): boolean {
  return matchesInboxScope(report, scope);
}

export interface InboxTabCounts {
  pulls: number;
  reports: number;
}

export const EMPTY_TAB_COUNTS: InboxTabCounts = {
  pulls: 0,
  reports: 0,
};

export function computeInboxTabCounts(
  reports: SignalReport[],
  scope: InboxScope,
): InboxTabCounts {
  const counts: InboxTabCounts = { ...EMPTY_TAB_COUNTS };
  for (const report of reports) {
    if (isExcludedFromInbox(report)) continue;
    if (!matchesReviewerScope(report, scope)) continue;
    if (isPullRequestReport(report)) counts.pulls += 1;
    if (isReportTabReport(report)) counts.reports += 1;
  }
  return counts;
}
