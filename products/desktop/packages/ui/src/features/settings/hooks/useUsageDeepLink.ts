import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { isSettingsCategory } from "@posthog/ui/features/settings/types";
import { navigateToSettings } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

const log = logger.scope("usage-deep-link");

/**
 * Handles Plan & usage deep links (`<scheme>://usage[/<category>]`, e.g.
 * `posthog-code://usage` for the Plan & usage page, or
 * `posthog-code://usage/agents` for another settings category) and opens the
 * matching settings page. Mirrors `useLoopDeepLink`: drains any link that
 * arrived before the renderer was ready and subscribes for links delivered
 * while the app is already running.
 */
export function useUsageDeepLink() {
  const trpcReact = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingUsageLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  const openUsage = useCallback((category: string) => {
    if (!isSettingsCategory(category)) {
      log.warn(
        `Usage deep link carried an unknown settings category: ${category}`,
      );
      return;
    }
    log.info(`Opening settings from deep link: category=${category}`);
    navigateToSettings(category);
  }, []);

  useEffect(() => {
    if (pendingDeepLink.data?.category) {
      openUsage(pendingDeepLink.data.category);
    }
  }, [pendingDeepLink.data, openUsage]);

  useSubscription(
    trpcReact.deepLink.onOpenUsage.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.category) openUsage(data.category);
      },
    }),
  );
}
