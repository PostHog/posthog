import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SpendAnalysisResponse } from "@posthog/api-client/spend-analysis";
import {
  averageDailySpend,
  spendTotalsFromDays,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

// One shared query: the guardrails watcher and the settings meters read the
// same personal spend snapshot instead of fetching twice.
export const SPEND_TOTALS_QUERY_KEY = ["billing", "spend-guardrails"] as const;

// Matches the spend analysis page scope so lines, meters, and charts agree.
export const SPEND_SCOPE_PRODUCT = "posthog_code";

// 30 UTC calendar days including today: always covers the current month.
const WINDOW_DAYS = 30;
const DATE_FROM = `-${WINDOW_DAYS - 1}dStart`;

export interface SpendSnapshot {
  todayUsd: number;
  monthUsd: number;
  /** Mean spend per day over the fetched window, zero days included. */
  avgDailyUsd: number;
}

export function fetchSpendWindow(
  client: PostHogAPIClient,
): Promise<SpendAnalysisResponse> {
  return client.getPersonalSpendAnalysis({
    dateFrom: DATE_FROM,
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
    staleTime: 60_000,
    retry: false,
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
