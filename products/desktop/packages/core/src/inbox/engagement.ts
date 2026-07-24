import type {
  InboxReportActionProperties,
  InboxReportActionSurface,
  InboxViewedProperties,
} from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/domain-types";
import {
  isPullRequestReport,
  isReportTabReport,
  orderedRunsTabReports,
} from "./reportMembership";

/** Originating inbox tab a report detail was opened from, derived from the route. */
export type InboxDetailTab = "pulls" | "reports" | "runs";

/**
 * The list of reports a detail screen's `rank` / `list_size` should be measured
 * against — i.e. the rows the originating tab actually rendered, in the order it
 * rendered them. Pure so it can be unit-tested and stays aligned with the tab
 * components.
 *
 * The Runs tab partitions and sorts into Queued → Live → Recently finished, so
 * runs reuse {@link orderedRunsTabReports} (the same selector `RunsTab` renders
 * from) rather than raw query order. That also pulls in finished runs, which
 * otherwise would report `rank: -1` against a list they aren't part of. The
 * Pull requests / Reports tabs render their filtered list in query order.
 */
export function inboxDetailTabReports(
  tab: InboxDetailTab,
  reports: SignalReport[],
): SignalReport[] {
  if (tab === "runs") {
    return orderedRunsTabReports(reports);
  }
  if (tab === "pulls") {
    return reports.filter(isPullRequestReport);
  }
  return reports.filter(isReportTabReport);
}

/** Report age at fire time in hours, rounded to one decimal. Clamped at 0 to guard against clock skew. */
export function reportAgeHours(createdAt: string | null | undefined): number {
  if (!createdAt) return 0;
  const ageMs = Date.now() - new Date(createdAt).getTime();
  if (!Number.isFinite(ageMs)) return 0;
  return Math.max(0, Math.round((ageMs / 3_600_000) * 10) / 10);
}

/** Live tracker snapshot for the currently-open report. */
export interface OpenReportSnapshot {
  reportId: string;
  rank: number;
  reportPriority: string | null;
  reportActionability: string | null;
}

export type ResolvedActionProperties = Pick<
  InboxReportActionProperties,
  "rank" | "list_size" | "priority" | "actionability"
>;

export interface ResolveActionPropertiesInput {
  reportId: string;
  rankOverride?: number;
  listSizeOverride?: number;
  priorityOverride?: string | null;
  actionabilityOverride?: string | null;
  openSnapshot: OpenReportSnapshot | null;
  visibleReports: SignalReport[];
}

/**
 * Resolve rank / list_size / priority / actionability for an INBOX_REPORT_ACTION event.
 *
 * Precedence: explicit override -> live open-info snapshot (current report only) ->
 * a one-shot lookup in the visible list. Callers firing after an async mutation should
 * pass pre-mutation overrides; by then the visible list has been re-queried without the
 * affected report.
 */
export function resolveActionProperties(
  input: ResolveActionPropertiesInput,
): ResolvedActionProperties {
  const {
    reportId,
    rankOverride,
    listSizeOverride,
    priorityOverride,
    actionabilityOverride,
    openSnapshot,
    visibleReports,
  } = input;

  const currentInfo =
    openSnapshot && openSnapshot.reportId === reportId ? openSnapshot : null;
  const matchedReport = currentInfo
    ? null
    : (visibleReports.find((r) => r.id === reportId) ?? null);

  const rank =
    rankOverride !== undefined
      ? rankOverride
      : currentInfo
        ? currentInfo.rank
        : visibleReports.findIndex((r) => r.id === reportId);
  const listSize =
    listSizeOverride !== undefined ? listSizeOverride : visibleReports.length;
  const priority =
    priorityOverride !== undefined
      ? priorityOverride
      : currentInfo
        ? currentInfo.reportPriority
        : (matchedReport?.priority ?? null);
  const actionability =
    actionabilityOverride !== undefined
      ? actionabilityOverride
      : currentInfo
        ? currentInfo.reportActionability
        : (matchedReport?.actionability ?? null);

  return { rank, list_size: listSize, priority, actionability };
}

/** Bulk-capable report actions fired from the selection toolbar / dismiss flows. */
export type InboxBulkActionType = Extract<
  InboxReportActionProperties["action_type"],
  "dismiss" | "snooze" | "delete" | "reingest"
>;

export interface BuildBulkActionEventsInput {
  /** Reports the action actually succeeded for (one event is built per report). */
  reports: SignalReport[];
  actionType: InboxBulkActionType;
  surface: InboxReportActionSurface;
  /** Dismissal metadata, only meaningful for `dismiss`. Note is truncated to 500 chars. */
  dismissal?: { reason?: string; note?: string };
}

/**
 * Build `INBOX_REPORT_ACTION` payloads for a bulk (or single-report) dismiss /
 * snooze / delete / reingest. Pure so it can be unit-tested and reused across
 * the toolbar, the per-row dismiss action, and detail-screen dismiss.
 *
 * `is_bulk` / `bulk_size` carry the grouping; `rank` / `list_size` are left at 0
 * because these flows act on a selection, not a positional list slot.
 */
export function buildBulkActionEvents(
  input: BuildBulkActionEventsInput,
): InboxReportActionProperties[] {
  const { reports, actionType, surface, dismissal } = input;
  const bulkSize = reports.length;
  const isBulk = bulkSize > 1;
  return reports.map((report) => ({
    report_id: report.id,
    report_title: report.title ?? null,
    report_age_hours: reportAgeHours(report.created_at),
    priority: report.priority ?? null,
    actionability: report.actionability ?? null,
    action_type: actionType,
    surface,
    is_bulk: isBulk,
    bulk_size: bulkSize,
    rank: 0,
    list_size: 0,
    ...(actionType === "dismiss" && dismissal?.reason
      ? { dismissal_reason: dismissal.reason }
      : {}),
    ...(actionType === "dismiss" && dismissal?.note
      ? { dismissal_note: dismissal.note.slice(0, 500) }
      : {}),
  }));
}

export interface InboxViewedFilterState {
  sourceProductFilter: string[];
  priorityFilter: string[];
  searchQuery: string;
  /**
   * True when the reviewer scope is the default ("For you"). False when the
   * user has narrowed to a teammate or the whole project — treated as an
   * active filter for `has_active_filters`.
   */
  isDefaultScope: boolean;
}

export interface BuildInboxViewedInput {
  /**
   * Reports currently visible to the user (after reviewer scope + search), used
   * for `report_count`, `ready_count`, and the priority/actionability breakdown.
   */
  visibleReports: SignalReport[];
  /** Server-reported total of reports matching the active query — the headline inbox number. */
  totalCount: number;
  /** Tab badge counts shown in the v2 header (the numbers the user actually sees). */
  tabCounts: { pulls: number; reports: number };
  filters: InboxViewedFilterState;
}

/**
 * Build the property payload for the `Inbox viewed` analytics event from the
 * v2 inbox state. Pure so it can be unit-tested and reused across hosts.
 *
 * v2 dropped the per-status and per-reviewer filter UI, so `status_filter_count`
 * is always 0 and `has_active_filters` is derived from the surviving source /
 * priority / search filters plus a non-default reviewer scope.
 */
export function buildInboxViewedProperties(
  input: BuildInboxViewedInput,
): InboxViewedProperties {
  const { visibleReports, totalCount, tabCounts, filters } = input;

  const priorityCounts = { P0: 0, P1: 0, P2: 0, P3: 0, P4: 0, unknown: 0 };
  const actionabilityCounts = {
    immediately_actionable: 0,
    requires_human_input: 0,
    not_actionable: 0,
    unknown: 0,
  };
  let readyCount = 0;
  for (const r of visibleReports) {
    if (r.status === "ready") readyCount += 1;
    const p = r.priority;
    if (p === "P0" || p === "P1" || p === "P2" || p === "P3" || p === "P4") {
      priorityCounts[p] += 1;
    } else {
      priorityCounts.unknown += 1;
    }
    const a = r.actionability;
    if (
      a === "immediately_actionable" ||
      a === "requires_human_input" ||
      a === "not_actionable"
    ) {
      actionabilityCounts[a] += 1;
    } else {
      actionabilityCounts.unknown += 1;
    }
  }

  const hasActiveFilters =
    filters.sourceProductFilter.length > 0 ||
    filters.priorityFilter.length > 0 ||
    filters.searchQuery.trim().length > 0 ||
    !filters.isDefaultScope;

  return {
    report_count: visibleReports.length,
    total_count: totalCount,
    ready_count: readyCount,
    has_active_filters: hasActiveFilters,
    source_product_filter: filters.sourceProductFilter,
    status_filter_count: 0,
    is_empty: totalCount === 0,
    priority_p0_count: priorityCounts.P0,
    priority_p1_count: priorityCounts.P1,
    priority_p2_count: priorityCounts.P2,
    priority_p3_count: priorityCounts.P3,
    priority_p4_count: priorityCounts.P4,
    priority_unknown_count: priorityCounts.unknown,
    actionability_immediately_actionable_count:
      actionabilityCounts.immediately_actionable,
    actionability_requires_human_input_count:
      actionabilityCounts.requires_human_input,
    actionability_not_actionable_count: actionabilityCounts.not_actionable,
    actionability_unknown_count: actionabilityCounts.unknown,
    pulls_count: tabCounts.pulls,
    reports_count: tabCounts.reports,
  };
}
