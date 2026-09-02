import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  navigateToChannel,
  navigateToChannelTask,
} from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

const log = logger.scope("channel-deep-link");

/**
 * Handles channel deep links (`<scheme>://channel/{channelId}` and
 * `<scheme>://channel/{channelId}/tasks/{taskId}`, e.g. `posthog-code://…` in
 * production and `posthog-code-dev://…` in local dev) and opens the channel —
 * or a thread inside it — in the Channels space. These arrive from a shareable
 * https link's web interstitial, so a teammate can open a channel straight in
 * the app.
 *
 * Mirrors `useCanvasDeepLink`: drains any link that arrived before the renderer
 * was ready (the main process clears its pending entry on read) and also
 * subscribes for links delivered while the app is already running. The live
 * subscription acts on every link unconditionally — gating it behind the
 * project-bluebird flag would drop a link that arrives before the flag resolves
 * (the main process emits rather than queues once a listener is attached, so a
 * discarded payload is unrecoverable). Navigation is safe regardless: the
 * Channels space is flag-gated at the route, which redirects out when off.
 */
export function useChannelDeepLink() {
  const trpcReact = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingChannelLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  const openChannel = useCallback((channelId: string, taskId?: string) => {
    log.info(
      `Opening channel from deep link: channelId=${channelId} taskId=${taskId ?? "-"}`,
    );
    track(ANALYTICS_EVENTS.DEEP_LINK_CHANNEL, {
      channel_id: channelId,
      task_id: taskId,
    });
    if (taskId) {
      navigateToChannelTask(channelId, taskId);
    } else {
      navigateToChannel(channelId);
    }
  }, []);

  useEffect(() => {
    const pending = pendingDeepLink.data;
    if (pending?.channelId) {
      openChannel(pending.channelId, pending.taskId);
    }
  }, [pendingDeepLink.data, openChannel]);

  useSubscription(
    trpcReact.deepLink.onOpenChannel.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.channelId) {
          openChannel(data.channelId, data.taskId);
        }
      },
    }),
  );
}
