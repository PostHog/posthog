import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { navigateToScoutDetail } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect } from "react";

const log = logger.scope("scout-deep-link");

/**
 * Hook that handles scout detail deep links (`<scheme>://scout/{skillSlug}?finding={id}`,
 * e.g. `posthog-code://…` in production and `posthog-code-dev://…` in local dev)
 * and opens the scout detail page, expanding the finding when one is supplied.
 *
 * Mirrors `useInboxDeepLink`: drains any link that arrived before the renderer
 * was ready (the main process clears its pending entry on read) and also
 * subscribes for links delivered while the app is already running.
 */
export function useScoutDeepLink() {
  const trpcReact = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingScoutLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  const openScout = useCallback((skillSlug: string, findingId?: string) => {
    log.info(
      `Opening scout from deep link: skillSlug=${skillSlug} findingId=${findingId ?? "(none)"}`,
    );
    navigateToScoutDetail(skillSlug, findingId);
  }, []);

  useEffect(() => {
    if (pendingDeepLink.data?.skillSlug) {
      openScout(pendingDeepLink.data.skillSlug, pendingDeepLink.data.findingId);
    }
  }, [pendingDeepLink.data, openScout]);

  useSubscription(
    trpcReact.deepLink.onOpenScout.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.skillSlug) openScout(data.skillSlug, data.findingId);
      },
    }),
  );
}
