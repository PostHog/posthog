import {
  buildChannelReportList,
  type ChannelReportSections,
  countChannelReportsByStatus,
  type ReportChannelView,
  type ReportStatusCounts,
  type ReportStatusFilter,
  splitChannelReportSections,
} from "@posthog/core/inbox/reportChannelScope";
import {
  buildSuggestedReviewerFilterParam,
  INBOX_DISMISSED_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";

/** Sidebar rows are small; a short first page paints fast and scroll streams the rest. */
const SIDEBAR_REPORTS_PAGE_SIZE = 25;

/** How long a fetched page stays fresh: remounts inside this window paint from cache with no refetch. */
const SIDEBAR_REPORTS_STALE_MS = 30_000;

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
  /**
   * The list split for the sidebar: a pinned needs-attention digest above the
   * chronological stream. Only the default browse state splits — a search,
   * status, or priority filter is already the user choosing what to look at,
   * so the pin would just reorder what they asked for.
   */
  sections: ChannelReportSections;
  isLoading: boolean;
  isError: boolean;
  /** Per-status-bucket counts under the current filters, for the status chips. */
  statusCounts: ReportStatusCounts;
  /** Whether the space has any unarchived reports at all — the tab dot. */
  hasReports: boolean;
  fetchNextPage: () => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
} {
  const channelId = view.kind === "channel" ? view.channelId : undefined;
  const enabled = options?.enabled ?? true;
  const archivedMode = filters.status === "archived";
  // "For you" is applied server-side via `suggested_reviewers`, mirroring the
  // inbox feed: the general space holds every report in the project, so
  // fetching only the scoped set is what keeps the sidebar fast — and it makes
  // the unread badge, the status counts, and the list read the same pages.
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const reviewerUuid = filters.relevantToMeOnly
    ? (currentUser?.uuid ?? null)
    : null;
  const suggestedReviewers = reviewerUuid
    ? buildSuggestedReviewerFilterParam([reviewerUuid])
    : undefined;
  // Hold the scoped query until the uuid resolves rather than firing a
  // throwaway project-wide fetch first.
  const scopeReady = !filters.relevantToMeOnly || reviewerUuid != null;
  const query = useInboxReportsInfinite(
    {
      ordering: "-updated_at",
      channel_id: channelId,
      suggested_reviewers: suggestedReviewers,
    },
    {
      enabled: enabled && scopeReady,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
      pageSize: SIDEBAR_REPORTS_PAGE_SIZE,
      staleTime: SIDEBAR_REPORTS_STALE_MS,
      // Toggling the scope or filters swaps the query key; keep showing the
      // pages already on screen while the new fetch runs instead of dropping
      // to a skeleton.
      placeholderData: keepPreviousData,
    },
  );
  // Archived reports are excluded from the main query server-side, so the
  // Archived bucket gets its own fetch, mounted only while selected.
  const archivedQuery = useInboxReportsInfinite(
    {
      status: INBOX_DISMISSED_STATUS_FILTER,
      ordering: "-updated_at",
      channel_id: channelId,
      suggested_reviewers: suggestedReviewers,
    },
    {
      enabled: enabled && archivedMode && scopeReady,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
      pageSize: SIDEBAR_REPORTS_PAGE_SIZE,
      staleTime: SIDEBAR_REPORTS_STALE_MS,
      placeholderData: keepPreviousData,
    },
  );

  const sourceReports = archivedMode
    ? archivedQuery.allReports
    : query.allReports;
  // Reviewer scope is already applied server-side; don't re-filter on the
  // `is_suggested_reviewer` boolean — it can disagree with that filter and
  // silently drop reports the fetch paid for.
  const reports = useMemo(
    () =>
      buildChannelReportList(sourceReports, {
        view,
        search: filters.search,
        relevantToMeOnly: false,
        priorities: filters.priorities,
        status: filters.status,
      }),
    [sourceReports, view, filters.search, filters.priorities, filters.status],
  );

  const defaultBrowse =
    !filters.search.trim() &&
    filters.status === "all" &&
    filters.priorities.length === 0;
  const sections = useMemo<ChannelReportSections>(
    () =>
      defaultBrowse
        ? splitChannelReportSections(reports)
        : { needsAttention: [], rest: reports },
    [reports, defaultBrowse],
  );

  const statusCounts = useMemo(() => {
    const counts = countChannelReportsByStatus(query.allReports, {
      view,
      search: filters.search,
      relevantToMeOnly: false,
      priorities: filters.priorities,
    });
    // Known only while the archived fetch is mounted; 0 reads as "not shown".
    counts.archived = archivedMode ? reports.length : 0;
    return counts;
  }, [
    query.allReports,
    view,
    filters.search,
    filters.priorities,
    archivedMode,
    reports.length,
  ]);

  // Pagination follows whichever query feeds the visible list, so the
  // Archived bucket pages through its own fetch.
  const activeQuery = archivedMode ? archivedQuery : query;
  return {
    reports,
    sections,
    statusCounts,
    // The main query excludes archived server-side, so any row means the space
    // has live reports (the tab dot's whole question).
    hasReports: query.allReports.length > 0,
    // Scope not resolved yet reads as loading, not as an empty list.
    isLoading: activeQuery.isLoading || !scopeReady,
    isError: activeQuery.isError,
    fetchNextPage: activeQuery.fetchNextPage,
    hasNextPage: activeQuery.hasNextPage ?? false,
    isFetchingNextPage: activeQuery.isFetchingNextPage,
  };
}
