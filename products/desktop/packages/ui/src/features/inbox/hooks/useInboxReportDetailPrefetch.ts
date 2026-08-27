import {
  INBOX_REPORT_DETAIL_STALE_TIME_MS,
  inboxReportDetailQueryKey,
} from "@posthog/core/inbox/inboxQuery";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";

export type InboxDetailRoute =
  | {
      to: "/inbox/pulls/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/inbox/reports/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/inbox/runs/$reportId";
      params: { reportId: string };
    }
  | {
      to: "/inbox/dismissed/$reportId";
      params: { reportId: string };
    };

interface InboxReportDetailPrefetch {
  prefetch: () => void;
  pointerHandlers: {
    onPointerEnter: () => void;
    onFocus: () => void;
    onPointerDown: () => void;
  };
}

/**
 * `<Link preload="intent">` warms route code on hover/focus. These handlers warm
 * the authenticated report request itself, which the route loader cannot do.
 */
export function useInboxReportDetailPrefetch(
  route: InboxDetailRoute | null,
): InboxReportDetailPrefetch {
  const queryClient = useQueryClient();
  const router = useRouter();
  const client = useOptionalAuthenticatedClient();

  // Callers build `route` inline each render, so use the route's stable id
  // pieces as deps instead of the object reference itself.
  const to = route?.to;
  const reportId = route?.params.reportId;
  const prefetchReport = useCallback(() => {
    if (!client || !reportId) return;
    void queryClient.prefetchQuery({
      queryKey: inboxReportDetailQueryKey(reportId),
      queryFn: () => client.getSignalReport(reportId),
      staleTime: INBOX_REPORT_DETAIL_STALE_TIME_MS,
      meta: AUTH_SCOPED_QUERY_META,
    });
  }, [client, queryClient, reportId]);

  const prefetch = useCallback(() => {
    prefetchReport();
    if (!to || !reportId) return;
    void router.preloadRoute({
      to,
      params: { reportId },
    } as InboxDetailRoute);
  }, [prefetchReport, reportId, router, to]);

  return useMemo(
    () => ({
      prefetch,
      pointerHandlers: {
        onPointerEnter: prefetchReport,
        onFocus: prefetchReport,
        onPointerDown: prefetchReport,
      },
    }),
    [prefetch, prefetchReport],
  );
}
