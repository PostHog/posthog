import {
  INBOX_REFETCH_INTERVAL_MS,
  INBOX_REPORTS_TAB_STATUS_FILTER,
} from "@posthog/core/inbox/reportFiltering";
import type { SignalReport } from "@posthog/shared/types";
import { useInboxReports } from "@posthog/ui/features/inbox/hooks/useInboxReports";

const P1_INBOX_ACTIVITY_PREVIEW_LIMIT = 3;
const EMPTY_REPORTS: SignalReport[] = [];

interface P1InboxActivityPreview {
  reports: SignalReport[];
  totalCount: number;
  isLoading: boolean;
}

export function useP1InboxActivityPreview(): P1InboxActivityPreview {
  const query = useInboxReports(
    {
      status: INBOX_REPORTS_TAB_STATUS_FILTER,
      ordering: "-updated_at",
      priority: "P1",
      limit: P1_INBOX_ACTIVITY_PREVIEW_LIMIT,
    },
    {
      refetchInterval: INBOX_REFETCH_INTERVAL_MS,
      refetchIntervalInBackground: false,
    },
  );

  return {
    reports: query.data?.results ?? EMPTY_REPORTS,
    totalCount: query.data?.count ?? 0,
    isLoading: query.isLoading,
  };
}
