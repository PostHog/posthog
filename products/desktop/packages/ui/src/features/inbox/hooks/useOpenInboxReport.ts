import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useReportSpace } from "@posthog/ui/features/canvas/hooks/useReportSpace";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const log = logger.scope("open-inbox-report");

export function useOpenInboxReport() {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const { reportSpaceId } = useReportSpace();

  return useCallback(
    async (reportId: string) => {
      if (!client) {
        log.warn("Ignoring open-report request – not authenticated");
        return;
      }
      if (!reportSpaceId) return;

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

        if (!report.canvas_session) {
          toast.error("This report's canvas isn't ready yet");
          return;
        }
        navigateToChannelDashboard(
          reportSpaceId,
          report.canvas_session.canvas_id,
        );
        log.info(`Successfully opened report: ${report.id}`);
      } catch (error) {
        log.error("Unexpected error opening report:", error);
        toast.error("Failed to open report");
      }
    },
    [client, queryClient, reportSpaceId],
  );
}
