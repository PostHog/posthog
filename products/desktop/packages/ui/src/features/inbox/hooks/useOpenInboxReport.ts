import { seedInboxReportDetailCache } from "@posthog/core/inbox/inboxQuery";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { toast } from "@posthog/ui/primitives/toast";
import {
  navigateToInboxDismissedDetail,
  navigateToInboxPullRequestDetail,
  navigateToInboxReportDetail,
} from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const log = logger.scope("open-inbox-report");

/**
 * Returns a callback that opens an inbox report by id: fetch it directly
 * (bypassing the paginated list), seed the detail cache, reset inbox-local
 * filters so it isn't hidden, then navigate to the right tab – Archive when
 * it's suppressed, Pulls when it has an implementation PR, otherwise Reports.
 *
 * Shared by the deep-link handler ({@link useInboxDeepLink}) and any in-app
 * surface that links to a report it only knows by id (e.g. the scout finding
 * → linked report chip). On 404/403 (wrong team / deleted) it toasts and
 * leaves the current view untouched.
 */
export function useOpenInboxReport() {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const resetFilters = useInboxSignalsFilterStore((s) => s.resetFilters);

  return useCallback(
    async (reportId: string) => {
      if (!client) {
        log.warn("Ignoring open-report request – not authenticated");
        return;
      }

      log.info(`Opening report: ${reportId}`);

      try {
        const report = await queryClient.fetchQuery({
          queryKey: reportKeys.detail(reportId),
          queryFn: () => client.getSignalReport(reportId),
          meta: AUTH_SCOPED_QUERY_META,
        });

        if (!report) {
          log.warn(`Report not found or not accessible: ${reportId}`);
          toast.error("Report not found in the current team");
          return;
        }

        resetFilters();
        seedInboxReportDetailCache(queryClient, report);
        if (report.status === "suppressed") {
          navigateToInboxDismissedDetail(report.id);
        } else if (report.implementation_pr_url) {
          navigateToInboxPullRequestDetail(report.id);
        } else {
          navigateToInboxReportDetail(report.id);
        }
        log.info(`Successfully opened report: ${report.id}`);
      } catch (error) {
        log.error("Unexpected error opening report:", error);
        toast.error("Failed to open report");
      }
    },
    [client, queryClient, resetFilters],
  );
}
