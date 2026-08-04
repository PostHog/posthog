import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { navigateToLoopDetail } from "@posthog/ui/router/navigationBridge";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useEffect } from "react";

export function useLoopDeepLink() {
  const trpcReact = useHostTRPC();
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

  useEffect(() => {
    if (pendingDeepLink.data?.loopId) {
      navigateToLoopDetail(pendingDeepLink.data.loopId);
    }
  }, [pendingDeepLink.data]);

  useSubscription(
    trpcReact.deepLink.onOpenLoop.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data?.loopId) navigateToLoopDetail(data.loopId);
      },
    }),
  );
}
