import { useHostTRPC } from "@posthog/host-router/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useOpenInboxReport } from "@posthog/ui/features/inbox/hooks/useOpenInboxReport";
import { navigateToInbox } from "@posthog/ui/router/navigationBridge";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

/**
 * Hook that subscribes to inbox report deep link events (`<scheme>://inbox/{reportId}`,
 * e.g. `posthog-code://…` in production and `posthog-code-dev://…` in local dev)
 * and opens the report in the inbox view. A link with no report segment
 * (`<scheme>://inbox`) opens the inbox itself.
 *
 * The actual open – fetch by id, seed the detail cache, reset filters, and
 * navigate to the right tab (Pulls if it has an implementation PR, otherwise
 * Reports) – lives in {@link useOpenInboxReport}, shared with other in-app
 * surfaces that link to a report by id. On 404/403 (wrong team / deleted /
 * suppressed) it toasts and leaves the current view untouched.
 */
export function useInboxDeepLink() {
  const trpcReact = useHostTRPC();
  const client = useOptionalAuthenticatedClient();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const openReport = useOpenInboxReport();
  const open = useCallback(
    (reportId: string | null): void => {
      if (reportId) {
        void openReport(reportId);
      } else {
        navigateToInbox();
      }
    },
    [openReport],
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingReportLink.queryOptions(undefined, {
      enabled: isAuthenticated && !!client,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  useEffect(() => {
    if (pendingDeepLink.data) {
      open(pendingDeepLink.data.reportId);
    }
  }, [pendingDeepLink.data, open]);

  useSubscription(
    trpcReact.deepLink.onOpenReport.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data) open(data.reportId);
      },
    }),
  );
}
