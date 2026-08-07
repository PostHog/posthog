import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { navigateToApproval } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useState } from "react";

const log = logger.scope("approval-deep-link");

/** A deep link that should open the ingress-backed approval modal. */
export interface PendingApprovalDeepLink {
  requestId: string;
  /** Agent slug — needed to address the slug-routed ingress. */
  agent: string;
}

/**
 * Handles agent approval deep links (`<scheme>://approval/{requestId}?agent=<slug>`).
 * The agent-runner emits these on a gated tool call so non-PostHog-Code clients
 * (MCP, a Slack link) can decide in the desktop app.
 *
 * When the link carries `?agent=<slug>` we open an ingress-backed modal: fetch +
 * decide go straight to the slug-routed ingress (principal-authed), so it works
 * from any project. A legacy link without a slug falls back to the
 * (project-scoped) fleet Approvals inbox.
 *
 * Mirrors `useScoutDeepLink`: drains a link that arrived before the renderer was
 * ready (the main process clears its pending entry on read) and subscribes for
 * links delivered while the app is already running. Returns the pending modal
 * target (or null) for a host component to render.
 */
export function useApprovalDeepLink(): {
  pending: PendingApprovalDeepLink | null;
  clear: () => void;
} {
  const trpcReact = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );
  const [pending, setPending] = useState<PendingApprovalDeepLink | null>(null);

  const open = useCallback((requestId: string, agent: string | null) => {
    if (agent) {
      log.info(`Opening approval modal: requestId=${requestId} agent=${agent}`);
      setPending({ requestId, agent });
    } else {
      // Legacy link with no slug — can't address the ingress; fall back to the
      // project-scoped fleet Approvals inbox.
      log.info(`Opening approval in inbox (no agent): requestId=${requestId}`);
      navigateToApproval(requestId);
    }
  }, []);

  const pendingDeepLink = useQuery(
    trpcReact.deepLink.getPendingApprovalLink.queryOptions(undefined, {
      enabled: isAuthenticated,
      // Drain once per session – the main process clears its pending entry on read.
      staleTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    }),
  );

  useEffect(() => {
    if (pendingDeepLink.data?.requestId) {
      open(pendingDeepLink.data.requestId, pendingDeepLink.data.agent);
    }
  }, [pendingDeepLink.data, open]);

  useSubscription(
    trpcReact.deepLink.onOpenApproval.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.requestId) open(data.requestId, data.agent);
      },
    }),
  );

  return { pending, clear: useCallback(() => setPending(null), []) };
}
