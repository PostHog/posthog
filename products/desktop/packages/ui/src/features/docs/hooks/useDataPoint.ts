import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type SeriesKind,
  seriesKind,
  seriesLabels,
  seriesPoints,
} from "@posthog/ui/features/docs/hooks/dataPointSeries";
import { formatMetric } from "@posthog/ui/features/docs/hooks/useInsightMetric";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/** A data point beside prose moves slowly; one read per minute is plenty. */
const DATA_POINT_STALE_MS = 60_000;

interface DataPointResult {
  value: string;
  /** The numbers of a series, in row order, for a small chart. Empty for one cell. */
  points: number[];
  /** One label per point. */
  labels: string[];
  seriesKind: SeriesKind | null;
  isLoading: boolean;
  isError: boolean;
  /** Why the query gave nothing, for the reader who hovers it. */
  error: string | null;
}

/**
 * The cell the page shows.
 *
 * A query is asked for one row and one column, and gets the first cell. When it
 * comes back wider than that, the number in the row is what the sentence meant:
 * a query grouped by day puts the day first and the count after it.
 */
export function firstCell(results: unknown[][] | undefined): unknown {
  const row = results?.[0];
  if (!Array.isArray(row)) return row;
  return row.find((cell) => typeof cell === "number") ?? row[0];
}

/** What a cell reads as beside prose. */
export function formatCell(cell: unknown): string | null {
  if (typeof cell === "number") return formatMetric(cell);
  if (typeof cell === "string") {
    const asNumber = Number(cell);
    return Number.isFinite(asNumber) && cell.trim() !== ""
      ? formatMetric(asNumber)
      : cell;
  }
  return null;
}

/** The line the query failed on, never the page a server sent instead of one. */
/** The `detail` of an API error body, when the message carries one. */
function apiErrorDetail(message: string): string | null {
  const start = message.indexOf("{");
  if (start === -1) return null;
  try {
    const body = JSON.parse(message.slice(start)) as { detail?: unknown };
    return typeof body.detail === "string" && body.detail.trim()
      ? body.detail.trim()
      : null;
  } catch {
    return null;
  }
}

/**
 * Why a query did not run, in one line a reader can act on. An API body says it
 * in `detail`; an HTML page or a bare status says nothing worth repeating.
 */
export function readQueryError(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  const message = error.message.trim();
  if (!message || message.includes("<!DOCTYPE") || message.includes("<html")) {
    return "This query did not run.";
  }
  const line = apiErrorDetail(message) ?? message.split("\n")[0];
  const said = /^[a-z]/.test(line) ? `This query did not run: ${line}` : line;
  return said.length > 160 ? `${said.slice(0, 159).trimEnd()}…` : said;
}

/**
 * One data point in a page, from the query the page keeps.
 *
 * The page stores the query and nothing else, so the value comes from the
 * project every time the page is read.
 */
export function useDataPoint(
  query: string,
  shape: "number" | "series" = "number",
): DataPointResult {
  const result = useAuthenticatedQuery(
    ["docs", "data-point", query],
    (client) => client.runHogQLQuery(query),
    {
      enabled: !!query,
      staleTime: DATA_POINT_STALE_MS,
      meta: AUTH_SCOPED_QUERY_META,
    },
  );

  const results = result.data?.results;
  const points = shape === "series" ? seriesPoints(results) : [];
  const kind = points.length ? seriesKind(results) : null;
  // A line ends in its latest point; columns add up to one total.
  const figure =
    kind === "time"
      ? points[points.length - 1]
      : kind === "categories"
        ? points.reduce((sum, point) => sum + point, 0)
        : firstCell(results);
  const value = formatCell(figure);
  const failed = readQueryError(result.error);

  return {
    value: value ?? "—",
    points,
    labels: points.length ? seriesLabels(results) : [],
    seriesKind: kind,
    isLoading: result.isLoading,
    isError: result.isError || (!result.isLoading && value === null),
    // A query that runs and returns nothing is as much a dead end as one that
    // does not run, so the reader gets a reason either way.
    error:
      failed ??
      (!result.isLoading && value === null
        ? "This query came back with nothing to show."
        : null),
  };
}
