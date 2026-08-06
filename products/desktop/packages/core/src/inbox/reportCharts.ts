import type { SignalReportChart } from "@posthog/shared/types";

/** Markdown link target prefix that marks a chart reference in a report summary. */
export const CHART_REF_PREFIX = "chart:";

// Matches the id charset the backend enforces on `chart_id`.
const CHART_REF_TARGET = /^chart:([a-z0-9][a-z0-9_-]*)$/;

/** Chart id from a `chart:<id>` link target, or null when the href is not one. */
export function parseChartRef(href: string | null | undefined): string | null {
  if (typeof href !== "string") return null;
  return CHART_REF_TARGET.exec(href)?.[1] ?? null;
}

export function findReportChart(
  charts: SignalReportChart[] | null | undefined,
  chartId: string,
): SignalReportChart | null {
  return charts?.find((chart) => chart.chart_id === chartId) ?? null;
}

export interface ChartOpenTarget {
  /** Project-relative path; callers prepend `/project/{id}` for the web app. */
  path: string;
  label: string;
}

// nginx accepts an 8 KiB request line by default, and that is the first thing
// in front of the app to refuse an over-long one. Sized against that rather
// than the browser's own much higher ceiling.
const MAX_OPEN_PATH_LENGTH = 8000;

// What an embedding surface sets to strip an insight down to its graph. A new
// insight wants the scene's own defaults for all of them, so they never travel
// in the URL.
const EMBED_PRESENTATION_KEYS = [
  "full",
  "embedded",
  "showFilters",
  "showHeader",
  "showTable",
  "showCorrelationTable",
  "showResults",
] as const;

function withoutEmbedFlags(query: Record<string, unknown>) {
  const node = { ...query };
  for (const key of EMBED_PRESENTATION_KEYS) {
    delete node[key];
  }
  return node;
}

function isHogQLQuery(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { kind?: unknown }).kind === "HogQLQuery"
  );
}

/**
 * Where a report chart's open control points in the PostHog web app, and what
 * to call it, mirroring the cloud inbox's routing: a `SavedInsightNode` opens
 * the insight it already points at, a SQL-backed node opens in the SQL editor,
 * anything else seeds a new insight from the query. `null` when there is
 * nowhere to send the reader, which is the caller's cue to drop the control
 * rather than offer a dead link.
 */
export function chartOpenTarget(query: unknown): ChartOpenTarget | null {
  if (typeof query !== "object" || query === null) {
    return null;
  }
  const node = query as Record<string, unknown>;

  if (node.kind === "SavedInsightNode") {
    // The query is stored unparsed, so the short id can be missing or not a
    // string at all. It is also caller-authored, hence the path-segment
    // encoding: a value like `../../settings` would otherwise resolve to an
    // unrelated scene.
    const shortId = node.shortId;
    if (typeof shortId !== "string" || !shortId) {
      return null;
    }
    return {
      path: `/insights/${encodeURIComponent(shortId)}`,
      label: "Open insight",
    };
  }

  const stripped = withoutEmbedFlags(node);
  const encoded = encodeURIComponent(JSON.stringify(stripped));

  let target: ChartOpenTarget;
  if (
    (node.kind === "DataVisualizationNode" || node.kind === "DataTableNode") &&
    isHogQLQuery(node.source)
  ) {
    target = {
      path: `/sql?open_query=${encoded}`,
      label: "Open in SQL editor",
    };
  } else {
    target = {
      path: `/insights/new#q=${encoded}`,
      label: "Open as new insight",
    };
  }

  // The control opens the URL as a real request, so a query near the backend's
  // size bound encodes past what a proxy in front of the app will accept and
  // the reader gets a 414. Nothing here can shorten it, so drop the control.
  if (target.path.length > MAX_OPEN_PATH_LENGTH) {
    return null;
  }
  return target;
}

// ── Native rendering ─────────────────────────────────────────────────────────
//
// The desktop app has no insight renderer, so report charts render through
// @posthog/quill-charts instead: the chart's source query runs through the
// `/query/` endpoint and the raw response is mapped to plain series here.
// Only the shapes report charts actually use are mapped (trends lines/bars,
// single numbers, SQL grids); everything else stays a link out to PostHog.

export type ReportChartRenderPlan =
  | {
      kind: "trends";
      /** Runnable source query to POST to `/query/`. */
      source: unknown;
      display: "line" | "bar" | "number";
      /** Accumulate values client-side (ActionsLineGraphCumulative). */
      cumulative: boolean;
    }
  | { kind: "sql"; source: unknown }
  | { kind: "link-only" };

const TRENDS_DISPLAY_MAP: Record<string, "line" | "bar" | "number"> = {
  ActionsLineGraph: "line",
  ActionsLineGraphCumulative: "line",
  ActionsAreaGraph: "line",
  ActionsBar: "bar",
  BoldNumber: "number",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * How to render a report chart's query natively, if at all. `InsightVizNode`
 * is a frontend-only wrapper, so its runnable `source` is what gets executed;
 * displays without a series mapping (pie, table, world map, …) and
 * `SavedInsightNode` (no query body to run) stay link-only.
 */
export function chartRenderPlan(query: unknown): ReportChartRenderPlan {
  const node = asRecord(query);
  if (!node) return { kind: "link-only" };

  if (node.kind === "InsightVizNode") {
    const source = asRecord(node.source);
    if (source?.kind !== "TrendsQuery") return { kind: "link-only" };
    const trendsFilter = asRecord(source.trendsFilter);
    const rawDisplay =
      typeof trendsFilter?.display === "string"
        ? trendsFilter.display
        : "ActionsLineGraph";
    const display = TRENDS_DISPLAY_MAP[rawDisplay];
    if (!display) return { kind: "link-only" };
    return {
      kind: "trends",
      source,
      display,
      cumulative: rawDisplay === "ActionsLineGraphCumulative",
    };
  }

  if (node.kind === "DataVisualizationNode" && isHogQLQuery(node.source)) {
    return { kind: "sql", source: node.source };
  }
  if (node.kind === "HogQLQuery") {
    return { kind: "sql", source: node };
  }

  return { kind: "link-only" };
}

// An inline chart link: `[label](chart:id)`, optionally with a link title.
const INLINE_CHART_LINK =
  /\[[^\]]*\]\(chart:([a-z0-9][a-z0-9_-]*)(?:\s+"[^"]*")?\)/g;

/**
 * Which of a report's charts should draw at their reference point in the
 * summary, per the cloud inbox's rule: a chart renders inline only when its
 * reference is all its paragraph holds (a block-level chart can't sit inside a
 * prose paragraph); every other chart renders after the summary. This is a
 * paragraph-block approximation of the cloud's markdown-parse version: a ref
 * nested in a list or blockquote may be judged inline here but rendered as a
 * link by the renderer, in which case the chart is reachable only through
 * that link.
 */
export function resolveInlineChartIds(
  summary: string | null | undefined,
  charts: SignalReportChart[] | null | undefined,
): Set<string> {
  const inline = new Set<string>();
  if (typeof summary !== "string" || !summary || !charts?.length) {
    return inline;
  }
  const available = new Set(charts.map((chart) => chart.chart_id));

  for (const block of summary.split(/\r?\n[ \t]*\r?\n/)) {
    const ids: string[] = [];
    const residue = block
      .replace(INLINE_CHART_LINK, (_match, id: string) => {
        ids.push(id);
        return "";
      })
      .replace(/<br\s*\/?>/gi, "")
      .replace(/\\$/gm, "")
      .trim();
    if (residue || ids.length === 0) continue;
    for (const id of ids) {
      if (available.has(id)) inline.add(id);
    }
  }
  return inline;
}

export interface ReportChartSeries {
  label: string;
  data: number[];
}

export interface ReportChartSeriesData {
  series: ReportChartSeries[];
  labels: string[];
  /** ISO dates for the x axis when the series is a day-bucketed trend. */
  days: string[] | null;
}

function toFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function runningSum(data: number[]): number[] {
  let total = 0;
  return data.map((value) => {
    total += value;
    return total;
  });
}

/**
 * Trends `/query/` response → chart series. The response shape is produced by
 * an agent-authored query, so anything that doesn't parse returns null and the
 * caller falls back to the link card instead of rendering a wrong chart.
 */
export function mapTrendsResults(
  response: unknown,
  options?: { cumulative?: boolean },
): ReportChartSeriesData | null {
  const rows = asRecord(response)?.results;
  if (!Array.isArray(rows) || rows.length === 0) return null;

  const series: ReportChartSeries[] = [];
  let labels: string[] | null = null;
  let days: string[] | null = null;

  for (const row of rows) {
    const record = asRecord(row);
    if (!record || !Array.isArray(record.data)) return null;
    const data = record.data.map(toFiniteNumber);
    if (data.some((value) => value === null)) return null;
    series.push({
      label: typeof record.label === "string" ? record.label : "",
      data: options?.cumulative
        ? runningSum(data as number[])
        : (data as number[]),
    });
    if (!labels && Array.isArray(record.labels)) {
      labels = record.labels.filter((l): l is string => typeof l === "string");
    }
    if (!days && Array.isArray(record.days)) {
      days = record.days.filter((d): d is string => typeof d === "string");
    }
  }

  const pointCount = series[0]?.data.length ?? 0;
  if (pointCount === 0) return null;
  if (series.some((s) => s.data.length !== pointCount)) return null;

  return {
    series,
    labels:
      labels && labels.length === pointCount
        ? labels
        : (days ?? []).length === pointCount
          ? (days as string[])
          : series[0].data.map((_, i) => String(i + 1)),
    days: days && days.length === pointCount ? days : null,
  };
}

/** BoldNumber trends response → the single aggregated value, or null. */
export function mapTrendsAggregatedValue(response: unknown): number | null {
  const rows = asRecord(response)?.results;
  if (!Array.isArray(rows)) return null;
  return toFiniteNumber(asRecord(rows[0])?.aggregated_value);
}

const ISO_DATE_LIKE = /^\d{4}-\d{2}-\d{2}/;

/**
 * HogQL `/query/` response (a column-named grid) → chart series: the first
 * column becomes the x axis, every all-numeric column a series. Null when the
 * grid has no numeric column or fewer than two rows, where a chart would not
 * say more than the link card.
 */
export function mapHogQLGridResults(
  response: unknown,
): ReportChartSeriesData | null {
  const record = asRecord(response);
  const columns = record?.columns;
  const rows = record?.results;
  if (!Array.isArray(columns) || !Array.isArray(rows) || rows.length < 2) {
    return null;
  }
  if (!rows.every((row): row is unknown[] => Array.isArray(row))) return null;

  const labels = rows.map((row) => String(row[0] ?? ""));
  const series: ReportChartSeries[] = [];
  for (let column = 1; column < columns.length; column++) {
    const data = rows.map((row) => toFiniteNumber(row[column]));
    if (data.some((value) => value === null)) continue;
    series.push({
      label: String(columns[column] ?? ""),
      data: data as number[],
    });
  }
  if (series.length === 0) return null;

  return {
    series,
    labels,
    days: labels.every((label) => ISO_DATE_LIKE.test(label)) ? labels : null,
  };
}
