import {
  buildChannelReportList,
  countChannelReportsByStatus,
  countChannelReportsForMe,
  type ReportChannelView,
  type ReportStatusCounts,
  type ReportStatusFilter,
} from "@posthog/core/inbox/reportChannelScope";
import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useMemo } from "react";

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
  fetchNextPage: () => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
} {
  const channelId = view.kind === "channel" ? view.channelId : undefined;
  const query = useInboxReportsInfinite(
    { ordering: "-updated_at", channel_id: channelId },
    {
      enabled: options?.enabled ?? true,
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    },
  );

  const reports = useMemo(
    () =>
      buildChannelReportList(query.allReports, {
        view,
        search: filters.search,
        relevantToMeOnly: filters.relevantToMeOnly,
        priorities: filters.priorities,
        status: filters.status,
      }),
    [
      query.allReports,
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

  const statusCounts = useMemo(
    () =>
      countChannelReportsByStatus(query.allReports, {
        view,
        search: filters.search,
        relevantToMeOnly: filters.relevantToMeOnly,
        priorities: filters.priorities,
      }),
    [
      query.allReports,
      view,
      filters.search,
      filters.relevantToMeOnly,
      filters.priorities,
    ],
  );

  return {
    reports,
    statusCounts,
    isLoading: query.isLoading,
    isError: query.isError,
    forMeCount,
    fetchNextPage: query.fetchNextPage,
    hasNextPage: query.hasNextPage ?? false,
    isFetchingNextPage: query.isFetchingNextPage,
  };
}
