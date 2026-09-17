import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  firstNumericCell,
  type GoalMeasure,
} from "@posthog/core/canvas/contextDocument";
import { insightCurrentValue } from "@posthog/core/canvas/goalMeasures";
import {
  deriveTrendSql,
  type TrendPeriod,
  trendPeriodFor,
} from "@posthog/ui/features/canvas/deriveTrendSql";
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
      staleTime: 0,
      refetchInterval: 60_000,
      retry: false,
    },
  );
}

export interface GoalTrendPoint {
  label: string;
  value: number;
}

export interface GoalTrend {
  period: TrendPeriod;
  points: GoalTrendPoint[];
}

export function goalTrendQuery(
  goalName: string,
  measure: GoalMeasure | null,
): { sql: string; period: TrendPeriod } | null {
  if (measure?.kind !== "hogql") return null;
  const period = trendPeriodFor(goalName, measure.sql);
  const derived = deriveTrendSql(measure.sql, period);
  if (derived) return derived;
  const explicit = measure.trendSql?.trim();
  return explicit ? { sql: explicit, period } : null;
}

export const goalTrendQueryKey = (
  goalName: string,
  measure: GoalMeasure | null,
) =>
  ["context-goal-trend", goalTrendQuery(goalName, measure)?.sql ?? ""] as const;

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

const BUCKET_COUNT: Record<TrendPeriod, number> = {
  day: 30,
  week: 12,
  month: 12,
};

function bucketKey(label: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(label.trim());
  return match ? match[1] : null;
}

function bucketStarts(period: TrendPeriod): Date[] {
  const now = new Date();
  const start = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
  if (period === "week")
    start.setUTCDate(start.getUTCDate() - start.getUTCDay());
  if (period === "month") start.setUTCDate(1);
  const starts: Date[] = [];
  for (let offset = BUCKET_COUNT[period] - 1; offset >= 0; offset -= 1) {
    const date = new Date(start);
    if (period === "day") date.setUTCDate(date.getUTCDate() - offset);
    if (period === "week") date.setUTCDate(date.getUTCDate() - offset * 7);
    if (period === "month") date.setUTCMonth(date.getUTCMonth() - offset);
    starts.push(date);
  }
  return starts;
}

/** Reads a goal's trend as one value per period, oldest first, with empty periods as zero. */
export function useGoalTrend(goalName: string, measure: GoalMeasure | null) {
  const query = goalTrendQuery(goalName, measure);
  return useAuthenticatedQuery<GoalTrend>(
    goalTrendQueryKey(goalName, measure),
    async (client) => {
      if (!query) return { period: "day", points: [] };
      const grid = await client.runHogQLQuery(query.sql);
      const byBucket = new Map<string, number>();
      for (const row of grid.results) {
        const value = lastNumericCell(row);
        const key = bucketKey(String(row[0] ?? ""));
        if (value !== null && key) byBucket.set(key, value);
      }
      const points = bucketStarts(query.period).map((start) => ({
        label: start.toISOString(),
        value: byBucket.get(start.toISOString().slice(0, 10)) ?? 0,
      }));
      return { period: query.period, points };
    },
    {
      enabled: query !== null,
      staleTime: 0,
      refetchInterval: 60_000,
      retry: false,
    },
  );
}
