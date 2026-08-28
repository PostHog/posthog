import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

const log = logger.scope("canvas-deep-link");

/**
 * Handles canvas deep links (`<scheme>://canvas/{channelId}/{dashboardId}`, e.g.
 * `posthog-code://…` in production and `posthog-code-dev://…` in local dev) and
 * opens the canvas in the Channels space. These arrive from a shareable https
 * link's web interstitial, so a teammate can open a canvas straight in the app.
 *
 * Mirrors `useScoutDeepLink`: drains any link that arrived before the renderer
 * was ready (the main process clears its pending entry on read) and also
 * subscribes for links delivered while the app is already running. The live
 * subscription acts on every link unconditionally — gating it behind the
 * project-bluebird flag would drop a link that arrives before the flag resolves
 * (the main process emits rather than queues once a listener is attached, so a
 * discarded payload is unrecoverable). Navigation is safe regardless: the
 * Channels space is flag-gated at the route, which redirects out when off.
 */
export function useCanvasDeepLink() {
  const trpcReact = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingCanvasLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  const openCanvas = useCallback((channelId: string, dashboardId: string) => {
    log.info(
      `Opening canvas from deep link: channelId=${channelId} dashboardId=${dashboardId}`,
    );
    track(ANALYTICS_EVENTS.DEEP_LINK_CANVAS, {
      channel_id: channelId,
      dashboard_id: dashboardId,
    });
    navigateToChannelDashboard(channelId, dashboardId);
  }, []);

  useEffect(() => {
    const pending = pendingDeepLink.data;
    if (pending?.channelId && pending?.dashboardId) {
      openCanvas(pending.channelId, pending.dashboardId);
    }
  }, [pendingDeepLink.data, openCanvas]);

  useSubscription(
    trpcReact.deepLink.onOpenCanvas.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.channelId && data?.dashboardId) {
          openCanvas(data.channelId, data.dashboardId);
        }
      },
    }),
  );
}
