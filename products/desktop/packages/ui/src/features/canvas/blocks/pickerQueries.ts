import { hostClient } from "@posthog/ui/features/canvas/hostClient";
import { useQuery } from "@tanstack/react-query";

export const TOP_EVENTS_HOGQL =
  "SELECT event, count() AS c FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event ORDER BY c DESC LIMIT 300";

export const TOP_EVENT_PROPERTIES_HOGQL =
  "SELECT k, count() AS c FROM (SELECT arrayJoin(JSONExtractKeys(properties)) AS k FROM events WHERE timestamp > now() - INTERVAL 7 DAY LIMIT 20000) GROUP BY k ORDER BY c DESC LIMIT 200";

export function useHogqlRows(hogql: string | null) {
  return useQuery({
    queryKey: ["canvas-block-hogql", hogql],
    queryFn: async (): Promise<unknown[][]> => {
      if (!hogql) return [];
      const result = await hostClient().canvasData.query.mutate({ hogql });
      return result.results as unknown[][];
    },
    enabled: hogql != null,
    staleTime: 10 * 60_000,
    retry: false,
  });
}

export function useSavedInsights() {
  return useQuery({
    queryKey: ["canvas-block-saved-insights"],
    queryFn: () => hostClient().canvasData.savedInsights.query(),
    staleTime: 60_000,
    retry: false,
  });
}
