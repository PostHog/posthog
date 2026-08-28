import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";

import {
  isDismissedReport,
  isExcludedFromInbox,
  isLiveRunReport,
  isQueuedRunReport,
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

/**
 * How many reports the needs-attention section may pin. A digest, not a
 * re-sort: past a handful the section stops answering "what should I look at
 * first" and becomes the same wall it was meant to cut through.
 */
export const NEEDS_ATTENTION_LIMIT = 5;

const PRIORITY_RANK: Record<SignalReportPriority, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

/**
 * Whether a report is waiting on a person right now: ready to act on, holding
 * a PR to review, stuck pending input, or failed and needing a call. Reports
 * the agent is still working (queued/live runs) never pin — there is nothing
 * to do about them yet.
 */
function reportNeedsPerson(report: SignalReport): boolean {
  return (
    !!report.implementation_pr_url ||
    report.status === "ready" ||
    report.status === "pending_input" ||
    report.status === "failed"
  );
}

export interface ChannelReportSections {
  /** Pinned digest: prioritized reports waiting on a person, P0 first. */
  needsAttention: SignalReport[];
  /** Everything else, newest-first — the chronological stream. */
  rest: SignalReport[];
}

/**
 * Split an already-built report list into the pinned needs-attention digest
 * and the chronological rest. Pinning requires a stated priority: the section
 * promises "most important first", and an unprioritized report has no claim to
 * that — it stays in the stream. Within the pin, priority outranks recency;
 * overflow past the cap falls back to the stream in its chronological place.
 */
export function splitChannelReportSections(
  orderedReports: SignalReport[],
): ChannelReportSections {
  const needsAttention = orderedReports
    .filter((report) => reportNeedsPerson(report) && report.priority != null)
    .sort((a, b) => {
      const rankDiff =
        PRIORITY_RANK[a.priority as SignalReportPriority] -
        PRIORITY_RANK[b.priority as SignalReportPriority];
      if (rankDiff !== 0) return rankDiff;
      return reportTimestampMs(b) - reportTimestampMs(a);
    })
    .slice(0, NEEDS_ATTENTION_LIMIT);
  const pinnedIds = new Set(needsAttention.map((report) => report.id));
  return {
    needsAttention,
    rest: orderedReports.filter((report) => !pinnedIds.has(report.id)),
  };
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
