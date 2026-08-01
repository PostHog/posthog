import { seedInboxReportDetailCache } from "@posthog/core/inbox/inboxQuery";
import type { SignalReport } from "@posthog/shared/types";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";

export type InboxDetailRoute =
  | {
      to: "/code/inbox/pulls/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/code/inbox/reports/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/code/inbox/runs/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/code/inbox/dismissed/$reportId";
      params: { reportId: string };
    };

/**
 * `<Link preload="intent">` already triggers route preload on hover/focus, so we
 * don't wire `onPointerEnter` here – that would double-fire `router.preloadRoute`
 * and run the destination loader for every card the cursor brushed.
 *
 * `onPointerDown` only seeds the detail-cache so a click navigation can resolve
 * the detail synchronously without flicker.
 */
export function useInboxReportDetailPrefetch(
  report: SignalReport,
  route: InboxDetailRoute,
) {
  const queryClient = useQueryClient();
  const router = useRouter();

  const seed = useCallback(() => {
    seedInboxReportDetailCache(queryClient, report);
  }, [queryClient, report]);

  // Callers build `route` inline each render, so use the route's stable id
  // pieces as deps instead of the object reference itself.
  const { to, params } = route;
  const reportId = params.reportId;
  const prefetch = useCallback(() => {
    seedInboxReportDetailCache(queryClient, report);
    void router.preloadRoute({
      to,
      params: { reportId },
    } as InboxDetailRoute);
  }, [queryClient, report, router, to, reportId]);

  return useMemo(
    () => ({
      prefetch,
      pointerHandlers: {
        onPointerDown: seed,
      },
    }),
    [prefetch, seed],
  );
}
