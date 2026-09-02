import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SpendAnalysisResponse } from "@posthog/api-client/spend-analysis";
import {
  type SpendAnalysisWindow,
  windowToDateFrom,
  windowToDays,
} from "@posthog/core/billing/spendAnalysisFormat";
import {
  averageDailySpend,
  spendTotalsFromDays,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

// The watcher needs spend to keep arriving to notice a line being crossed.
const POLL_INTERVAL_MS = 5 * 60_000;

// Matches the spend analysis page scope so lines, meters, and charts agree.
const SPEND_SCOPE_PRODUCT = "posthog_code";

// 30 UTC calendar days including today: always covers the current month.
const SPEND_WINDOW: SpendAnalysisWindow = "30d";
const WINDOW_DAYS = windowToDays(SPEND_WINDOW);

// The same key shape useSpendAnalysis uses, so opening Plan & usage at this
// window reads this cache entry instead of fetching the endpoint again.
const SPEND_TOTALS_QUERY_KEY = [
  "billing",
  "spend-analysis",
  SPEND_WINDOW,
  SPEND_SCOPE_PRODUCT,
] as const;

export interface SpendSnapshot {
  todayUsd: number;
  monthUsd: number;
  /** Mean spend per day over the fetched window, zero days included. */
  avgDailyUsd: number;
}

function fetchSpendWindow(
  client: PostHogAPIClient,
): Promise<SpendAnalysisResponse> {
  return client.getPersonalSpendAnalysis({
    dateFrom: windowToDateFrom(SPEND_WINDOW),
    product: SPEND_SCOPE_PRODUCT,
  });
}

/**
 * Today's and this month's personal spend in this app, or null while the
 * data hasn't loaded (or the endpoint is unavailable).
 */
export function useSpendTotals(): SpendSnapshot | null {
  const client = useOptionalAuthenticatedClient();
  const enabled = useSpendAnalysisEnabled();
  const query = useQuery({
    queryKey: SPEND_TOTALS_QUERY_KEY,
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return fetchSpendWindow(client);
    },
    enabled: client !== null && enabled,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 60_000,
    retry: false,
    // Personal billing data: drop it on any auth transition so a new account
    // never reads the previous one's spend from the shared cache key.
    meta: AUTH_SCOPED_QUERY_META,
  });
  const days = query.data?.by_day?.items;
  return useMemo(() => {
    if (!days) return null;
    return {
      ...spendTotalsFromDays(days, utcDayIso()),
      avgDailyUsd: averageDailySpend(days, WINDOW_DAYS),
    };
  }, [days]);
}
