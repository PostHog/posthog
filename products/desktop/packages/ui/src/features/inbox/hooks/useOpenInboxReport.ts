import { useService } from "@posthog/di/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { focusOrOpenBrowserTab } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { reportKeys } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToReport } from "@posthog/ui/router/navigationBridge";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const log = logger.scope("open-inbox-report");

export function useOpenInboxReport() {
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const tabsClient = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);

  return useCallback(
    async (
      reportId: string,
      options?: { preserveSource?: boolean; newTab?: boolean },
    ) => {
      const sourceKey = getRouterOrNull()?.history.location.state.__TSR_key;
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

        if (getRouterOrNull()?.history.location.state.__TSR_key !== sourceKey)
          return;
        if (options?.newTab) {
          await focusOrOpenBrowserTab(tabsClient, {
            href: `/reports/${report.id}`,
            appView: "report",
          });
        } else {
          navigateToReport(report.id, options);
        }
        log.info(`Successfully opened report: ${report.id}`);
      } catch (error) {
        log.error("Unexpected error opening report:", error);
        toast.error("Failed to open report");
      }
    },
    [client, queryClient, tabsClient],
  );
}
