import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/** Insight numbers move slowly next to a doc; one read per minute is plenty. */
const METRIC_STALE_MS = 60_000;

interface InsightMetricResult {
  value: string;
  isLoading: boolean;
  isError: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The one number an insight is worth showing beside prose.
 *
 * Insight results come in several shapes, so this reads them in order of how
 * specific they are: an aggregate first, then a total, then the last point of a
 * series, then the first cell of a table. Anything else has no single number.
 */
export function headlineNumber(results: unknown): number | null {
  if (!Array.isArray(results) || results.length === 0) return null;
  const first = results[0];

  if (isRecord(first)) {
    if (typeof first.aggregated_value === "number")
      return first.aggregated_value;
    if (typeof first.count === "number") return first.count;
    if (Array.isArray(first.data)) {
      const points = first.data.filter(
        (point): point is number => typeof point === "number",
      );
      if (points.length > 0) return points[points.length - 1];
    }
    return null;
  }

  if (Array.isArray(first) && typeof first[0] === "number") return first[0];
  if (typeof first === "number") return first;
  return null;
}

/** Groups thousands and keeps at most one decimal, so a row of numbers lines up. */
export function formatMetric(value: number): string {
  const rounded =
    Math.abs(value) < 100 ? Math.round(value * 10) / 10 : Math.round(value);
  return rounded.toLocaleString();
}

/** One saved insight, read live and reduced to a single number. */
export function useInsightMetric(shortId: string): InsightMetricResult {
  const query = useAuthenticatedQuery(
    ["docs", "insight-metric", shortId],
    (client) => client.getInsightDefinition(shortId),
    {
      enabled: !!shortId,
      staleTime: METRIC_STALE_MS,
      meta: AUTH_SCOPED_QUERY_META,
    },
  );

  const number = headlineNumber(query.data?.response?.results);

  return {
    // A dash rather than a sentence: an insight with no single number should
    // stay quiet in a row of numbers instead of shouting about itself.
    value: number === null ? "—" : formatMetric(number),
    isLoading: query.isLoading,
    isError: query.isError,
  };
}
