import type { SignalReportChartSize } from "@posthog/shared/types";

type QueryNode = Record<string, unknown>;

export type ReportChartRender = "line" | "bar" | "number" | "auto";

/**
 * What to do with a chart's stored query. The backend only guarantees the
 * top-level `kind`, so anything else in the node is treated as untrusted JSON:
 * `run` means the source query can be executed via `/query/` and drawn with
 * quill-charts, `saved-insight` and `open-only` degrade to a card that links
 * out to PostHog, and `invalid` drops the chart body entirely.
 */
export type ReportChartPlan =
  | { kind: "run"; source: QueryNode; render: ReportChartRender }
  | { kind: "saved-insight"; shortId: string }
  | { kind: "open-only" }
  | { kind: "invalid" };

function isRecord(value: unknown): value is QueryNode {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function renderFromDisplay(display: unknown): ReportChartRender {
  if (display === "BoldNumber") return "number";
  if (display === "ActionsBar" || display === "ActionsBarValue") return "bar";
  if (display === "ActionsLineGraph" || display === "ActionsAreaGraph") {
    return "line";
  }
  return "auto";
}

export function planReportChart(query: unknown): ReportChartPlan {
  if (!isRecord(query) || typeof query.kind !== "string") {
    return { kind: "invalid" };
  }
  if (query.kind === "SavedInsightNode") {
    return typeof query.shortId === "string" && query.shortId
      ? { kind: "saved-insight", shortId: query.shortId }
      : { kind: "invalid" };
  }
  const source = isRecord(query.source) ? query.source : null;
  if (query.kind === "InsightVizNode") {
    if (!source) return { kind: "invalid" };
    if (source.kind !== "TrendsQuery" && source.kind !== "StickinessQuery") {
      return { kind: "open-only" };
    }
    const filter =
      source.kind === "TrendsQuery"
        ? source.trendsFilter
        : source.stickinessFilter;
    const display = isRecord(filter) ? filter.display : undefined;
    const render = renderFromDisplay(display);
    return {
      kind: "run",
      source,
      render: render === "auto" ? "line" : render,
    };
  }
  if (query.kind === "DataVisualizationNode") {
    if (!source || source.kind !== "HogQLQuery") {
      return { kind: "open-only" };
    }
    return { kind: "run", source, render: renderFromDisplay(query.display) };
  }
  return { kind: "open-only" };
}

/**
 * Ids of the charts that will actually mount a card (`invalid` plans render
 * nothing), so summary `chart:` links only become in-page jumps when a target
 * exists.
 */
export function renderableReportChartIds(
  charts: readonly { chart_id: string; query: unknown }[] | undefined,
): string[] {
  return (charts ?? [])
    .filter((chart) => planReportChart(chart.query).kind !== "invalid")
    .map((chart) => chart.chart_id);
}

export interface ReportChartSeries {
  key: string;
  label: string;
  data: number[];
}

export type ReportChartData =
  | {
      type: "series";
      render: "line" | "bar";
      labels: string[];
      series: ReportChartSeries[];
      isTimeSeries: boolean;
      interval: "hour" | "day";
    }
  | { type: "number"; value: number }
  | { type: "table"; columns: string[]; rows: unknown[][] }
  | { type: "empty" };

const MAX_SERIES = 15;
const MAX_TABLE_ROWS = 100;

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}/;

function isDateLike(value: unknown): value is string {
  return (
    typeof value === "string" &&
    (DATE_ONLY.test(value) || DATE_TIME.test(value))
  );
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function intervalFor(labels: string[]): "hour" | "day" {
  return labels.some((label) => DATE_TIME.test(label)) ? "hour" : "day";
}

const MIDNIGHT_STAMP =
  /^(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?(?:Z|[+-]\d{2}:?\d{2})?$/;

/**
 * Day-bucketed results arrive as midnight timestamps carrying the project's
 * UTC offset (`2026-07-26T00:00:00-07:00`). Formatting those in any fixed
 * timezone can shift the calendar day, so when every label is a midnight
 * stamp the time component is dropped and the backend's bucket date is the
 * label.
 */
function normalizeDayLabels(labels: string[]): string[] {
  if (labels.length === 0) return labels;
  const matches = labels.map((label) => MIDNIGHT_STAMP.exec(label));
  if (matches.some((match) => match === null)) return labels;
  return matches.map((match) => (match as RegExpExecArray)[1]);
}

function shapeTrendsResponse(
  response: QueryNode,
  render: ReportChartRender,
): ReportChartData {
  const results = Array.isArray(response.results) ? response.results : [];
  const seriesResults = results.filter(isRecord);
  if (seriesResults.length === 0) return { type: "empty" };

  if (render === "number") {
    const total = seriesResults.reduce((sum, result) => {
      const aggregated = asFiniteNumber(result.aggregated_value);
      if (aggregated !== null) return sum + aggregated;
      const data = Array.isArray(result.data) ? result.data : [];
      return (
        sum + data.reduce<number>((s, v) => s + (asFiniteNumber(v) ?? 0), 0)
      );
    }, 0);
    return { type: "number", value: total };
  }

  const first = seriesResults[0];
  const labels = (
    Array.isArray(first.days) ? first.days : (first.labels ?? [])
  ) as unknown[];
  const stringLabels = normalizeDayLabels(labels.map(String));
  if (stringLabels.length === 0) return { type: "empty" };

  const series = seriesResults.slice(0, MAX_SERIES).map((result, index) => {
    const data = (Array.isArray(result.data) ? result.data : []).map(
      (v) => asFiniteNumber(v) ?? 0,
    );
    return {
      key: `series-${index}`,
      label:
        typeof result.label === "string" && result.label
          ? result.label
          : `Series ${index + 1}`,
      data,
    };
  });
  return {
    type: "series",
    render: render === "bar" ? "bar" : "line",
    labels: stringLabels,
    series,
    isTimeSeries: stringLabels.every(isDateLike),
    interval: intervalFor(stringLabels),
  };
}

function pivotBreakdownGrid(
  rows: unknown[][],
  columns: string[],
): { labels: string[]; series: ReportChartSeries[] } | null {
  const rawLabels = [...new Set(rows.map((row) => String(row[0])))];
  const labels = normalizeDayLabels(rawLabels);
  const breakdowns = [...new Set(rows.map((row) => String(row[1])))];
  if (breakdowns.length > MAX_SERIES) return null;
  // Rows are looked up by their raw first-column value; only the displayed
  // labels are normalized.
  const labelIndex = new Map(rawLabels.map((label, i) => [label, i]));
  const series = breakdowns.map((name, index) => ({
    key: `breakdown-${index}`,
    label: name || columns[1] || `Series ${index + 1}`,
    data: labels.map(() => 0),
  }));
  const seriesByName = new Map(breakdowns.map((name, i) => [name, series[i]]));
  for (const row of rows) {
    const target = seriesByName.get(String(row[1]));
    const position = labelIndex.get(String(row[0]));
    if (target && position !== undefined) {
      target.data[position] = asFiniteNumber(row[2]) ?? 0;
    }
  }
  return { labels, series };
}

function shapeHogQLResponse(
  response: QueryNode,
  render: ReportChartRender,
): ReportChartData {
  const rows = (Array.isArray(response.results) ? response.results : []).filter(
    (row): row is unknown[] => Array.isArray(row),
  );
  const columns = (Array.isArray(response.columns) ? response.columns : []).map(
    String,
  );
  if (rows.length === 0) return { type: "empty" };

  const singleValue =
    rows.length === 1 && rows[0].length === 1
      ? asFiniteNumber(rows[0][0])
      : null;
  if (render === "number" || (render === "auto" && singleValue !== null)) {
    const value =
      singleValue ??
      rows
        .flat()
        .map(asFiniteNumber)
        .find((v) => v !== null);
    return value !== null && value !== undefined
      ? { type: "number", value }
      : asTable(rows, columns);
  }

  if (render === "line" || render === "bar") {
    const firstColumnDates = rows.every((row) => isDateLike(row[0]));
    const width = rows[0].length;
    const numericTail = (row: unknown[]): boolean =>
      row.slice(1).every((cell) => asFiniteNumber(cell) !== null);

    if (width === 3 && firstColumnDates && !numericTail(rows[0])) {
      const pivoted = pivotBreakdownGrid(rows, columns);
      if (pivoted && rows.every((row) => asFiniteNumber(row[2]) !== null)) {
        return {
          type: "series",
          render,
          labels: pivoted.labels,
          series: pivoted.series,
          isTimeSeries: true,
          interval: intervalFor(pivoted.labels),
        };
      }
    }
    if (width >= 2 && rows.every(numericTail)) {
      const labels = normalizeDayLabels(rows.map((row) => String(row[0])));
      const series = columns.slice(1, 1 + MAX_SERIES).map((column, index) => ({
        key: `column-${index}`,
        label: column || `Series ${index + 1}`,
        data: rows.map((row) => asFiniteNumber(row[index + 1]) ?? 0),
      }));
      return {
        type: "series",
        render,
        labels,
        series,
        isTimeSeries: firstColumnDates,
        interval: intervalFor(labels),
      };
    }
  }

  return asTable(rows, columns);
}

function asTable(rows: unknown[][], columns: string[]): ReportChartData {
  return { type: "table", columns, rows: rows.slice(0, MAX_TABLE_ROWS) };
}

/**
 * Shape a raw `/query/` response into a drawable model. The response shape
 * depends on the source kind: trends return `results` as series objects,
 * HogQL returns a `columns` + `results` grid.
 */
export function shapeReportChartData(
  response: QueryNode,
  plan: Extract<ReportChartPlan, { kind: "run" }>,
): ReportChartData {
  if (
    plan.source.kind === "TrendsQuery" ||
    plan.source.kind === "StickinessQuery"
  ) {
    return shapeTrendsResponse(response, plan.render);
  }
  return shapeHogQLResponse(response, plan.render);
}

const SIZE_HEIGHTS: Record<SignalReportChartSize, string> = {
  small: "h-36",
  medium: "h-72",
  large: "h-[28rem]",
};
const SIZE_MAX_HEIGHTS: Record<SignalReportChartSize, string> = {
  small: "max-h-36",
  medium: "max-h-72",
  large: "max-h-[28rem]",
};

/**
 * A graph fills whatever box it is given, so it takes a fixed height; a table
 * or number sizes to its content and only needs a ceiling to scroll within.
 * Follows the web inbox sizing: `size` on the chart wins, numbers default
 * small, everything else medium.
 */
export function reportChartHeightClass(
  size: SignalReportChartSize | null | undefined,
  data: ReportChartData | null,
): string {
  const valid = size && size in SIZE_HEIGHTS ? size : null;
  if (data?.type === "series") {
    return SIZE_HEIGHTS[valid ?? "medium"];
  }
  if (data?.type === "number") {
    return SIZE_MAX_HEIGHTS[valid ?? "small"];
  }
  return SIZE_MAX_HEIGHTS[valid ?? "medium"];
}

export interface ReportChartOpenTarget {
  url: string;
  label: string;
}

// nginx refuses request lines past 8 KiB, and a chart query can be up to 20k
// chars of JSON before encoding, so an over-long URL is dropped rather than
// offered as a link that 414s.
const MAX_OPEN_URL_LENGTH = 8000;

const EMBED_PRESENTATION_KEYS = [
  "full",
  "embedded",
  "showFilters",
  "showHeader",
  "showTable",
  "showCorrelationTable",
  "showResults",
] as const;

function withoutEmbedFlags(query: QueryNode): QueryNode {
  const node = { ...query };
  for (const key of EMBED_PRESENTATION_KEYS) {
    delete node[key];
  }
  return node;
}

/**
 * Where a chart's "open in PostHog" control points. Returns null when there is
 * nowhere safe to send the reader (missing saved-insight id, or a query too
 * large to fit in a URL), which is the caller's cue to drop the control.
 */
export function reportChartOpenTarget(
  query: unknown,
  options: { cloudUrl: string; projectId: number | string },
): ReportChartOpenTarget | null {
  if (!isRecord(query) || typeof query.kind !== "string") return null;
  const projectBase = `${options.cloudUrl}/project/${options.projectId}`;

  if (query.kind === "SavedInsightNode") {
    if (typeof query.shortId !== "string" || !query.shortId) return null;
    return {
      url: `${projectBase}/insights/${encodeURIComponent(query.shortId)}`,
      label: "Open insight",
    };
  }

  const node = withoutEmbedFlags(query);
  const source = isRecord(node.source) ? node.source : null;
  const isHogQLBacked =
    (node.kind === "DataVisualizationNode" || node.kind === "DataTableNode") &&
    source?.kind === "HogQLQuery";

  let url: string;
  let label: string;
  if (node.kind === "HogQLQuery" && typeof node.query === "string") {
    url = `${projectBase}/sql?open_query=${encodeURIComponent(node.query)}`;
    label = "Open in SQL editor";
  } else if (isHogQLBacked) {
    url = `${projectBase}/sql?open_query=${encodeURIComponent(JSON.stringify(node))}`;
    label = "Open in SQL editor";
  } else {
    url = `${projectBase}/insights/new?q=${encodeURIComponent(JSON.stringify(node))}`;
    label = "Open as new insight";
  }
  return url.length > MAX_OPEN_URL_LENGTH ? null : { url, label };
}
