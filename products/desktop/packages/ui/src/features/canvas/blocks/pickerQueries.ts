import { hostClient } from "@posthog/ui/features/canvas/hostClient";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

export const TOP_EVENTS_HOGQL =
  "SELECT event, count() AS c FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event ORDER BY c DESC LIMIT 300";

export const TOP_EVENT_PROPERTIES_HOGQL =
  "SELECT k, count() AS c FROM (SELECT arrayJoin(JSONExtractKeys(properties)) AS k FROM events WHERE timestamp > now() - INTERVAL 7 DAY LIMIT 20000) GROUP BY k ORDER BY c DESC LIMIT 200";

export function useTopValues(hogql: string) {
  return useQuery({
    queryKey: ["canvas-block-hogql", hogql],
    queryFn: async (): Promise<string[]> => {
      const result = await hostClient().canvasData.query.mutate({ hogql });
      return (result.results as unknown[][]).map((row) => String(row[0]));
    },
    staleTime: 10 * 60_000,
    retry: false,
  });
}

export function useSavedInsights(search: string) {
  return useQuery({
    queryKey: ["canvas-block-saved-insights", search],
    queryFn: () => hostClient().canvasData.savedInsights.query({ search }),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  });
}
