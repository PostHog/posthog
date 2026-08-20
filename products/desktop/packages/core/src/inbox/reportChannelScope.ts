import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";

import {
  isDismissedReport,
  isExcludedFromInbox,
  isLiveRunReport,
  isQueuedRunReport,
  matchesInboxScope,
} from "./reportMembership";

/**
 * How the sidebar Reports list is scoped to a space. The general space is the
 * catch-all: it lists every report regardless of assignment. Any other space
 * lists only the reports assigned to it (`report.channel_id === channelId`).
 */
export type ReportChannelView =
  | { kind: "general" }
  | { kind: "channel"; channelId: string };

export function generalReportView(): ReportChannelView {
  return { kind: "general" };
}

export function channelReportView(channelId: string): ReportChannelView {
  return { kind: "channel", channelId };
}

function reportMatchesChannelView(
  report: SignalReport,
  view: ReportChannelView,
): boolean {
  if (view.kind === "general") return true;
  return report.channel_id === view.channelId;
}

/**
 * The old inbox tabs reborn as a filter. Every non-archived report falls in
 * exactly one bucket: an implementation PR puts it in needs-review; ready
 * without a PR is ready; everything still moving (queued, live) plus failed
 * runs is running — the same population the inbox's Runs tab held.
 */
export type ReportStatusFilter =
  | "all"
  | "needs-review"
  | "ready"
  | "running"
  | "archived";

export function matchesReportStatusFilter(
  report: SignalReport,
  filter: ReportStatusFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "archived") return isDismissedReport(report);
  if (filter === "needs-review") return !!report.implementation_pr_url;
  if (filter === "ready") {
    return report.status === "ready" && !report.implementation_pr_url;
  }
  return (
    isQueuedRunReport(report) ||
    isLiveRunReport(report) ||
    report.status === "failed"
  );
}

export interface ChannelReportListOptions {
  view: ReportChannelView;
  /** When true, keep only reports the current user is a suggested reviewer for. */
  relevantToMeOnly?: boolean;
  /** Case-insensitive substring match against the report title. */
  search?: string;
  /** Keep only reports at one of these priorities; empty means no priority filter. */
  priorities?: SignalReportPriority[];
  /** Keep only reports in this lifecycle bucket; "all" (the default) keeps every one. */
  status?: ReportStatusFilter;
}

function reportTimestampMs(report: SignalReport): number {
  const value = report.updated_at ?? report.created_at;
  if (!value) return 0;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

function matchesChannelReportOptions(
  report: SignalReport,
  options: ChannelReportListOptions,
): boolean {
  const status = options.status ?? "all";
  // "archived" is the one bucket made of the statuses every other bucket
  // excludes, so it swaps the exclusion instead of stacking on it.
  if (status === "archived") {
    if (!isDismissedReport(report)) return false;
  } else {
    if (isExcludedFromInbox(report)) return false;
    if (!matchesReportStatusFilter(report, status)) return false;
  }
  if (!reportMatchesChannelView(report, options.view)) return false;
  if (options.relevantToMeOnly && report.is_suggested_reviewer !== true) {
    return false;
  }
  if (options.priorities && options.priorities.length > 0) {
    if (!report.priority || !options.priorities.includes(report.priority)) {
      return false;
    }
  }
  const search = options.search?.trim().toLowerCase();
  if (search) {
    const title = report.title?.toLowerCase() ?? "";
    if (!title.includes(search)) return false;
  }
  return true;
}

/**
 * The ordered list the Reports surfaces render. Suppressed, resolved, and
 * deleted reports drop out (they live behind the Archived bucket); the rest are
 * narrowed by the space scope and the active filters, then sorted newest-first.
 * Pure so the ordering the user sees is testable without a render.
 */
export function buildChannelReportList(
  reports: SignalReport[],
  options: ChannelReportListOptions,
): SignalReport[] {
  return reports
    .filter((report) => matchesChannelReportOptions(report, options))
    .sort((a, b) => reportTimestampMs(b) - reportTimestampMs(a));
}

export type ReportStatusCounts = Record<ReportStatusFilter, number>;

/**
 * How many reports each status bucket would show under the current view and
 * filters — the numbers on the status chips. The status filter itself is
 * ignored, so a chip's count doesn't change when it is selected.
 */
export function countChannelReportsByStatus(
  reports: SignalReport[],
  options: Omit<ChannelReportListOptions, "status">,
): ReportStatusCounts {
  const counts: ReportStatusCounts = {
    all: 0,
    "needs-review": 0,
    ready: 0,
    running: 0,
    // Archived rows come from a separate fetch, so their count is stamped by
    // the caller once that list is loaded.
    archived: 0,
  };
  for (const report of reports) {
    if (!matchesChannelReportOptions(report, { ...options, status: "all" })) {
      continue;
    }
    counts.all += 1;
    if (matchesReportStatusFilter(report, "needs-review")) {
      counts["needs-review"] += 1;
    } else if (matchesReportStatusFilter(report, "ready")) {
      counts.ready += 1;
    } else {
      counts.running += 1;
    }
  }
  return counts;
}

/**
 * How many active reports in this space arrived after the user last looked at
 * its Reports surface — the Slack-style unread badge. No stamp yet (first run)
 * counts as caught-up rather than flooding the badge with history.
 */
export function countUnseenReports(
  reports: SignalReport[],
  view: ReportChannelView,
  seenAt: string | undefined,
): number {
  if (!seenAt) return 0;
  return reports.filter(
    (report) =>
      matchesChannelReportOptions(report, { view }) &&
      report.created_at > seenAt,
  ).length;
}

/** Newest active report's arrival, the stamp `countUnseenReports` compares against. */
export function latestReportArrival(
  reports: SignalReport[],
  view: ReportChannelView,
): string | null {
  let latest: string | null = null;
  for (const report of reports) {
    if (!matchesChannelReportOptions(report, { view })) continue;
    if (!latest || report.created_at > latest) latest = report.created_at;
  }
  return latest;
}

/** Count for the tab badge: reports in this space the user should notice. */
export function countChannelReportsForMe(
  reports: SignalReport[],
  view: ReportChannelView,
): number {
  return reports.filter(
    (report) =>
      !isExcludedFromInbox(report) &&
      reportMatchesChannelView(report, view) &&
      matchesInboxScope(report, "for-you"),
  ).length;
}
