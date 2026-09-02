import { isDateLike } from "@posthog/core/inbox/reportCharts";

/** How a series reads: points along time, or one figure per category. */
export type SeriesKind = "time" | "categories";

/** The number in each row, for a query that gives a label and a number per row. */
export function seriesPoints(results: unknown[][] | undefined): number[] {
  if (!results || results.length < 2) return [];
  const points: number[] = [];
  for (const row of results) {
    if (!Array.isArray(row)) return [];
    const cell = row.find((value) => typeof value === "number");
    if (typeof cell !== "number") return [];
    points.push(cell);
  }
  return points;
}

/**
 * Dates draw a line; anything else draws columns, the same call the chart card
 * makes. A row with no label at all counts as a step in time.
 */
export function seriesKind(results: unknown[][] | undefined): SeriesKind {
  const labels = (results ?? []).map((row) =>
    row.find((value) => typeof value !== "number"),
  );
  return labels.every((label) => label === undefined || isDateLike(label))
    ? "time"
    : "categories";
}

/** The label in each row, as words: a day, an event name, whatever the query grouped by. */
export function seriesLabels(results: unknown[][] | undefined): string[] {
  return (results ?? []).map((row) => {
    const label = row.find((value) => typeof value !== "number");
    return label === undefined || label === null ? "" : String(label);
  });
}
