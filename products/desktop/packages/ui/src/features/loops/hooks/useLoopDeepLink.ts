import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import { focusOrOpenBrowserTab } from "@posthog/ui/features/browser-tabs/imperativeTabNavigation";
import { navigateToLoopDetail } from "@posthog/ui/router/navigationBridge";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

export function useLoopDeepLink() {
  const trpcReact = useHostTRPC();
  const tabsClient = useService<BrowserTabsClient>(BROWSER_TABS_CLIENT);
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingLoopLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  const openLoop = useCallback(
    (loopId: string): void => {
      void focusOrOpenBrowserTab(tabsClient, {
        href: `/loops/${loopId}`,
        appView: "loops",
      }).then((handled) => {
        if (handled) return;
        navigateToLoopDetail(loopId);
      });
    },
    [tabsClient],
  );

  useEffect(() => {
    if (pendingDeepLink.data?.loopId) {
      openLoop(pendingDeepLink.data.loopId);
    }
  }, [pendingDeepLink.data, openLoop]);

  useSubscription(
    trpcReact.deepLink.onOpenLoop.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.loopId) openLoop(data.loopId);
      },
    }),
  );
}
