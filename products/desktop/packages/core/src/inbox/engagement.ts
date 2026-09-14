import type {
  InboxReportActionProperties,
  InboxReportActionSurface,
  InboxReviewerScope,
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

/** Bulk-capable report actions fired from the selection toolbar / dismiss flows. */
export type InboxBulkActionType = Extract<
  InboxReportActionProperties["action_type"],
  "dismiss" | "snooze" | "delete" | "reingest" | "remove_suggested_reviewer"
>;

export interface BuildBulkActionEventsInput {
  /** Reports the action actually succeeded for (one event is built per report). */
  reports: SignalReport[];
  actionType: InboxBulkActionType;
  surface: InboxReportActionSurface;
  triageId?: string;
  bulkSize?: number;
  /** Dismissal category, only meaningful for `dismiss`. */
  dismissalReason?: string;
}

/**
 * Build `INBOX_REPORT_ACTION` payloads for a bulk (or single-report) dismiss /
 * snooze / delete / reingest / remove-suggested-reviewer. Pure so it can be
 * unit-tested and reused across the toolbar, the per-row dismiss action, and
 * detail-screen dismiss.
 *
 * `is_bulk` / `bulk_size` carry the grouping; `rank` / `list_size` are left at 0
 * because these flows act on a selection, not a positional list slot.
 */
export function buildBulkActionEvents(
  input: BuildBulkActionEventsInput,
): InboxReportActionProperties[] {
  const { reports, actionType, surface, triageId, dismissalReason } = input;
  const bulkSize = input.bulkSize ?? reports.length;
  const isBulk = bulkSize > 1;
  return reports.map((report) => ({
    report_id: report.id,
    report_age_hours: reportAgeHours(report.created_at),
    priority: report.priority ?? null,
    actionability: report.actionability ?? null,
    action_type: actionType,
    surface,
    is_bulk: isBulk,
    bulk_size: bulkSize,
    rank: 0,
    list_size: 0,
    ...(triageId ? { triage_id: triageId } : {}),
    ...(actionType === "dismiss" && dismissalReason
      ? { dismissal_reason: dismissalReason }
      : {}),
  }));
}

interface InboxViewedFilterStateBase {
  sourceProductFilter: string[];
  priorityFilter: string[];
}

interface DesktopInboxViewedFilterState extends InboxViewedFilterStateBase {
  surface: "desktop";
  searchQuery: string;
  /** Canonical scope value. Teammate UUIDs must not enter analytics. */
  scope: InboxReviewerScope;
  /** Selected report-state filter keys shown above the list. */
  reportStateFilter: readonly string[];
  /** Default report-state selection, used to detect a non-default filter. */
  defaultReportStateFilter: readonly string[];
}

interface MobileInboxViewedFilterState extends InboxViewedFilterStateBase {
  surface: "mobile";
  statusFilter: readonly string[];
  defaultStatusFilter: readonly string[];
  suggestedReviewerFilter: string[];
}

interface BuildInboxViewedInputBase {
  /**
   * Reports currently visible to the user (after reviewer scope + search), used
   * for `report_count`, `ready_count`, and the priority/actionability breakdown.
   */
  visibleReports: SignalReport[];
  /** Server-reported total of reports matching the active query — the headline inbox number. */
  totalCount: number;
}

export type BuildInboxViewedInput =
  | (BuildInboxViewedInputBase & {
      filters: DesktopInboxViewedFilterState;
      /** Tab badge counts shown in the desktop header. */
      tabCounts?: { pulls: number; reports: number };
    })
  | (BuildInboxViewedInputBase & {
      filters: MobileInboxViewedFilterState;
      tabCounts?: never;
    });

/** Whether a filter selection differs from its default set (order-insensitive). */
function differsFromDefault(
  selected: readonly string[],
  defaults: readonly string[],
): boolean {
  return (
    selected.length !== defaults.length ||
    selected.some((value) => !defaults.includes(value))
  );
}

/**
 * Build the property payload for the `Inbox viewed` analytics event from the
 * v2 inbox state. Pure so it can be unit-tested and reused across hosts.
 *
 * `status_filter_count` and `has_active_filters` reflect each surface's own
 * status control: the mobile status filter or the desktop report-state filter,
 * alongside the shared source / priority / search filters and a non-default scope.
 */
export function buildInboxViewedProperties(
  input: BuildInboxViewedInput,
): InboxViewedProperties {
  const { visibleReports, totalCount, filters } = input;
  const tabCounts = input.tabCounts;

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

  const statusFiltered =
    filters.surface === "mobile"
      ? differsFromDefault(filters.statusFilter, filters.defaultStatusFilter)
      : differsFromDefault(
          filters.reportStateFilter,
          filters.defaultReportStateFilter,
        );
  const hasActiveFilters =
    filters.sourceProductFilter.length > 0 ||
    filters.priorityFilter.length > 0 ||
    (filters.surface === "desktop" && filters.searchQuery.trim().length > 0) ||
    statusFiltered ||
    (filters.surface === "mobile" &&
      filters.suggestedReviewerFilter.length > 0) ||
    (filters.surface === "desktop" && filters.scope !== "for-you");

  return {
    report_count: visibleReports.length,
    total_count: totalCount,
    ready_count: readyCount,
    has_active_filters: hasActiveFilters,
    source_product_filter: filters.sourceProductFilter,
    status_filter_count:
      filters.surface === "mobile"
        ? filters.statusFilter.length
        : filters.reportStateFilter.length,
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
    ...(filters.surface === "desktop" ? { scope: filters.scope } : {}),
    ...(tabCounts
      ? {
          pulls_tab_count: tabCounts.pulls,
          reports_tab_count: tabCounts.reports,
        }
      : {}),
  };
}
