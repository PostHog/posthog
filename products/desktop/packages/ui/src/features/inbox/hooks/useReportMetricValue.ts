import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import {
  planReportMetricQuery,
  readReportMetricSeries,
  readReportMetricTotal,
} from "@posthog/core/inbox/reportMetrics";
import type { SignalReportMetric } from "@posthog/shared/types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

export interface LiveReportMetricValue {
  value: number;
  series: number[] | null;
}

/**
 * Runs a metric's stored query so the report shows what it measures now. The
 * whole-window value comes from the BoldNumber shape and the buckets from the
 * ActionsBar shape, which is what the backend refresh runs too, so both sides
 * read the same cache entries and never sum per-bucket unique counts.
 *
 * A metric whose query is absent, redacted, or a shape this app cannot run
 * stays on its saved snapshot, and so does a metric whose query fails.
 */
export function useReportMetricValue(
  reportId: string,
  metric: SignalReportMetric,
): {
  data: LiveReportMetricValue | undefined;
  isPending: boolean;
  isError: boolean;
} {
  const plan = useMemo(
    () => planReportMetricQuery(metric.query),
    [metric.query],
  );

  const query = useAuthenticatedQuery<LiveReportMetricValue>(
    inboxReportKeys.metricValue(reportId, metric.metric_id),
    async (client) => {
      if (!plan) throw new Error("Metric query cannot be run here");
      const [total, series] = await Promise.all([
        client.runQuery(plan.total),
        client.runQuery(plan.series).catch(() => null),
      ]);
      const value = readReportMetricTotal(total);
      if (value === null) throw new Error("Metric query returned no value");
      return { value, series: series ? readReportMetricSeries(series) : null };
    },
    {
      enabled: plan !== null,
      staleTime: 15 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );

  return {
    data: query.data,
    isPending: plan !== null && query.isPending,
    isError: query.isError,
  };
}
