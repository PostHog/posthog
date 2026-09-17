import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  firstNumericCell,
  type GoalMeasure,
} from "@posthog/core/canvas/contextDocument";
import { insightCurrentValue } from "@posthog/core/canvas/goalMeasures";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export const goalMeasureQueryKey = (measure: GoalMeasure | null) =>
  [
    "context-goal-measure",
    measure?.kind ?? "none",
    measure?.kind === "hogql" ? measure.sql : (measure?.shortId ?? ""),
  ] as const;

/** Reads a goal's current value from its measure. */
export async function readGoalMeasure(
  client: PostHogAPIClient,
  measure: GoalMeasure,
): Promise<number | null> {
  if (measure.kind === "hogql") {
    const grid = await client.runHogQLQuery(measure.sql);
    return firstNumericCell(grid.results);
  }
  const insight = await client.getInsightDefinition(measure.shortId);
  return insightCurrentValue(insight?.response?.results);
}

export function useGoalMeasure(measure: GoalMeasure | null) {
  return useAuthenticatedQuery<number | null>(
    goalMeasureQueryKey(measure),
    (client) =>
      measure ? readGoalMeasure(client, measure) : Promise.resolve(null),
    {
      enabled:
        measure !== null &&
        (measure.kind === "insight" || measure.sql.trim().length > 0),
      // A goal's number changes slowly; re-running every mount would hit
      // ClickHouse once per tile each time the page opens.
      staleTime: 5 * 60_000,
      retry: false,
    },
  );
}

export const goalTrendQueryKey = (measure: GoalMeasure | null) =>
  [
    "context-goal-trend",
    measure?.kind === "hogql" ? (measure.trendSql ?? "") : "",
  ] as const;

function lastNumericCell(row: unknown[]): number | null {
  for (let index = row.length - 1; index >= 0; index -= 1) {
    const cell = row[index];
    if (typeof cell === "number" && Number.isFinite(cell)) return cell;
    if (typeof cell === "string" && cell.trim() !== "") {
      const parsed = Number(cell);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

/** Reads a goal's trend as one value per period, oldest first. */
export function useGoalTrend(measure: GoalMeasure | null) {
  const trendSql =
    measure?.kind === "hogql" ? (measure.trendSql ?? "").trim() : "";
  return useAuthenticatedQuery<number[]>(
    goalTrendQueryKey(measure),
    async (client) => {
      if (!trendSql) return [];
      const grid = await client.runHogQLQuery(trendSql);
      return grid.results
        .map(lastNumericCell)
        .filter((value): value is number => value !== null);
    },
    { enabled: trendSql.length > 0, staleTime: 5 * 60_000, retry: false },
  );
}
