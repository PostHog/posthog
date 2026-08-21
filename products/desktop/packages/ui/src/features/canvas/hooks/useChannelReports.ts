import {
  buildChannelReportList,
  countChannelReportsByStatus,
  countChannelReportsForMe,
  countUnseenReports,
  latestReportArrival,
  type ReportChannelView,
  type ReportStatusCounts,
  type ReportStatusFilter,
} from "@posthog/core/inbox/reportChannelScope";
import { INBOX_DISMISSED_STATUS_FILTER } from "@posthog/core/inbox/reportFiltering";
import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";
import {
  reportViewKey,
  useReportSeenStore,
} from "@posthog/ui/features/canvas/stores/reportSeenStore";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useCallback, useMemo } from "react";

export interface ChannelReportsFilters {
  search: string;
  relevantToMeOnly: boolean;
  priorities: SignalReportPriority[];
  status: ReportStatusFilter;
}

export const EMPTY_CHANNEL_REPORTS_FILTERS: ChannelReportsFilters = {
  search: "",
  relevantToMeOnly: false,
  priorities: [],
  status: "all",
};

/**
 * What a Reports surface starts on: scoped to reports suggested for the
 * current user. The general space holds every report in the project, so the
 * unfiltered list is both noisy and expensive to render; one funnel click
 * widens to everything.
 */
export const DEFAULT_CHANNEL_REPORTS_FILTERS: ChannelReportsFilters = {
  ...EMPTY_CHANNEL_REPORTS_FILTERS,
  relevantToMeOnly: true,
};

/**
 * The reports shown in a space's Reports tab. The general space fetches every
 * report; any other space fetches only its own (`channel_id`). Server results
 * are then narrowed client-side by the tab's search / priority / for-you
 * filters, reusing the pure {@link buildChannelReportList}.
 */
export function useChannelReports(
  view: ReportChannelView,
  filters: ChannelReportsFilters,
  options?: { enabled?: boolean },
): {
  reports: SignalReport[];
  isLoading: boolean;
  isError: boolean;
  forMeCount: number;
  /** Per-status-bucket counts under the current filters, for the status chips. */
  statusCounts: ReportStatusCounts;
  /** Active reports newer than the last time this view's reports were looked at. */
  unseenCount: number;
  /** Stamp this view's reports seen up to the newest arrival. */
  markSeen: () => void;
  fetchNextPage: () => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
} {
  const channelId = view.kind === "channel" ? view.channelId : undefined;
  const enabled = options?.enabled ?? true;
  const archivedMode = filters.status === "archived";
  const query = useInboxReportsInfinite(
    { ordering: "-updated_at", channel_id: channelId },
    {
      enabled,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    },
  );
  // Archived reports are excluded from the main query server-side, so the
  // Archived bucket gets its own fetch, mounted only while selected.
  const archivedQuery = useInboxReportsInfinite(
    {
      status: INBOX_DISMISSED_STATUS_FILTER,
      ordering: "-updated_at",
      channel_id: channelId,
    },
    {
      enabled: enabled && archivedMode,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    },
  );

  const sourceReports = archivedMode
    ? archivedQuery.allReports
    : query.allReports;
  const reports = useMemo(
    () =>
      buildChannelReportList(sourceReports, {
        view,
        search: filters.search,
        relevantToMeOnly: filters.relevantToMeOnly,
        priorities: filters.priorities,
        status: filters.status,
      }),
    [
      sourceReports,
      view,
      filters.search,
      filters.relevantToMeOnly,
      filters.priorities,
      filters.status,
    ],
  );

  const forMeCount = useMemo(
    () => countChannelReportsForMe(query.allReports, view),
    [query.allReports, view],
  );

  const statusCounts = useMemo(() => {
    const counts = countChannelReportsByStatus(query.allReports, {
      view,
      search: filters.search,
      relevantToMeOnly: filters.relevantToMeOnly,
      priorities: filters.priorities,
    });
    // Known only while the archived fetch is mounted; 0 reads as "not shown".
    counts.archived = archivedMode ? reports.length : 0;
    return counts;
  }, [
    query.allReports,
    view,
    filters.search,
    filters.relevantToMeOnly,
    filters.priorities,
    archivedMode,
    reports.length,
  ]);

  const viewKey = reportViewKey(view);
  const seenAt = useReportSeenStore((s) => s.seenAtByView[viewKey]);
  const hasHydrated = useReportSeenStore((s) => s.hasHydrated);
  const markReportsSeen = useReportSeenStore((s) => s.markReportsSeen);
  const unseenCount = useMemo(
    () => countUnseenReports(query.allReports, view, seenAt),
    [query.allReports, view, seenAt],
  );
  const latestArrival = useMemo(
    () => latestReportArrival(query.allReports, view),
    [query.allReports, view],
  );
  const markSeen = useCallback(() => {
    if (!hasHydrated || !latestArrival) return;
    markReportsSeen(viewKey, latestArrival);
  }, [hasHydrated, latestArrival, markReportsSeen, viewKey]);

  // Pagination follows whichever query feeds the visible list, so the
  // Archived bucket pages through its own fetch.
  const activeQuery = archivedMode ? archivedQuery : query;
  return {
    reports,
    statusCounts,
    unseenCount,
    markSeen,
    isLoading: activeQuery.isLoading,
    isError: activeQuery.isError,
    forMeCount,
    fetchNextPage: activeQuery.fetchNextPage,
    hasNextPage: activeQuery.hasNextPage ?? false,
    isFetchingNextPage: activeQuery.isFetchingNextPage,
  };
}
