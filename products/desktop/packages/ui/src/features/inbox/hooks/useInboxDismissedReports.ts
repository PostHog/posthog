import {
  buildArchiveListOrdering,
  INBOX_DISMISSED_STATUS_FILTER,
  INBOX_REFETCH_INTERVAL_MS,
} from "@posthog/core/inbox/reportFiltering";
import { useInboxReportsInfinite } from "@posthog/ui/features/inbox/hooks/useInboxReports";

/**
 * Archived reports for the Archive tab — suppressed (user-dismissed) and
 * resolved (implementation PR merged). These are excluded from the main pipeline
 * query, so they get a dedicated fetch.
 *
 * Polls while focused: dismiss/restore invalidate `reportKeys.all` locally, but
 * `resolved` is a server-side transition (a PR merges) with no client-side
 * trigger, so without polling a freshly-resolved report wouldn't surface in an
 * open Archive tab until an unrelated remount or focus refetch. Newest-changed
 * first via `updated_at` (last state change).
 */
export function useInboxDismissedReports() {
  const query = useInboxReportsInfinite(
    {
      status: INBOX_DISMISSED_STATUS_FILTER,
      ordering: buildArchiveListOrdering("updated_at", "desc"),
    },
    { refetchInterval: INBOX_REFETCH_INTERVAL_MS },
  );

  return {
    ...query,
    reports: query.allReports,
  };
}
