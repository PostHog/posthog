import { inboxReportKeys } from "@posthog/core/inbox/inboxQuery";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * Runs a report chart's source query through the project `/query/` endpoint.
 * Report charts pin absolute date ranges, so results stay valid long enough to
 * cache for the visit.
 */
export function useReportChartData(
  reportId: string,
  chartId: string,
  source: unknown,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<unknown>(
    inboxReportKeys.chartData(reportId, chartId, source),
    (client) => client.runInsightQueryNode(source),
    {
      enabled: options?.enabled ?? true,
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );
}
