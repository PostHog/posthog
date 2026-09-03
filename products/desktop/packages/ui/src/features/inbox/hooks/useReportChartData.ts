import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import {
  type ReportChartData,
  type ReportChartPlan,
  shapeReportChartData,
} from "@posthog/core/inbox/reportCharts";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

/**
 * Executes a report chart's source query and shapes the response for
 * rendering. Only fires for `run` plans; saved-insight and fallback cards
 * never hit the network. Chart results are evidence snapshots, so they are
 * cached long client-side and served cache-first by the backend
 * (`refresh: "blocking"`).
 */
export function useReportChartData(
  reportId: string,
  chartId: string,
  plan: ReportChartPlan,
): UseQueryResult<ReportChartData> {
  return useAuthenticatedQuery<ReportChartData>(
    inboxReportKeys.chartData(reportId, chartId),
    async (client) => {
      if (plan.kind !== "run") return { type: "empty" };
      const response = await client.runQuery(plan.source);
      return shapeReportChartData(response, plan);
    },
    {
      enabled: plan.kind === "run",
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );
}
