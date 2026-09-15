import { firstNumericCell } from "@posthog/core/canvas/contextDocument";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export const goalMeasureQueryKey = (sql: string) =>
  ["context-goal-measure", sql] as const;

/** Runs a goal's HogQL and reads the current value from its first cell. */
export function useGoalMeasure(sql: string) {
  return useAuthenticatedQuery<number | null>(
    goalMeasureQueryKey(sql),
    async (client) => {
      const grid = await client.runHogQLQuery(sql);
      return firstNumericCell(grid.results);
    },
    {
      enabled: sql.trim().length > 0,
      // A goal's number changes slowly; re-running every mount would hit
      // ClickHouse once per card each time the page opens.
      staleTime: 5 * 60_000,
      retry: false,
    },
  );
}
