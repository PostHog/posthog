import type { SignalReportChartSize } from "@posthog/shared/types";

type QueryNode = Record<string, unknown>;

export type ReportChartRender = "line" | "bar" | "number" | "table" | "auto";

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
  if (display === "BoldNumber" || display === "Metric") return "number";
  if (
    display === "ActionsBar" ||
    display === "ActionsUnstackedBar" ||
    display === "ActionsStackedBar" ||
    display === "ActionsBarValue" ||
    display === "ActionsPie"
  ) {
    return "bar";
  }
  if (
    display === "ActionsLineGraph" ||
    display === "ActionsAreaGraph" ||
    display === "ActionsLineGraphCumulative"
  ) {
    return "line";
  }
  if (display === "ActionsTable" || display === "WorldMap") return "table";
  return "auto";
}

function trendsRenderFromDisplay(
  display: unknown,
  sourceKind: "TrendsQuery" | "StickinessQuery",
): ReportChartRender | null {
  if (display === undefined || display === "Auto") {
    return sourceKind === "StickinessQuery" ? "bar" : "line";
  }
  if (
    display === "CalendarHeatmap" ||
    display === "TwoDimensionalHeatmap" ||
    display === "BoxPlot" ||
    display === "SlopeGraph" ||
    display === "ScatterPlot"
  ) {
    return null;
  }
  return renderFromDisplay(display);
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
    // Lifecycle results share the trends series shape, and PostHog draws them
    // as bars; run them rather than degrade to a link-out card.
    if (source.kind === "LifecycleQuery") {
      return { kind: "run", source, render: "bar" };
    }
    // Only the step visualization maps onto a categorical bar chart; the
    // trends and time-to-convert visualizations have different result shapes.
    if (source.kind === "FunnelsQuery") {
      const filter = isRecord(source.funnelsFilter)
        ? source.funnelsFilter
        : null;
      const vizType = filter?.funnelVizType;
      if (vizType !== undefined && vizType !== "steps") {
        return { kind: "open-only" };
      }
      // Compare merges current and previous periods into one response the
      // categorical bar chart cannot disambiguate, so degrade to a link-out card.
      const compareFilter = isRecord(source.compareFilter)
        ? source.compareFilter
        : null;
      if (compareFilter?.compare === true) {
        return { kind: "open-only" };
      }
      return { kind: "run", source, render: "bar" };
    }
    if (source.kind !== "TrendsQuery" && source.kind !== "StickinessQuery") {
      return { kind: "open-only" };
    }
    const filter =
      source.kind === "TrendsQuery"
        ? source.trendsFilter
        : source.stickinessFilter;
    const display = isRecord(filter) ? filter.display : undefined;
    const render = trendsRenderFromDisplay(display, source.kind);
    return render ? { kind: "run", source, render } : { kind: "open-only" };
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

/** 87342 -> "87.3K"; keeps small numbers plain without reading a nonzero value as 0. */
function compactChartValue(value: number): string {
  const abs = Math.abs(value);
  const format = (scaled: number, suffix: string): string => {
    const rounded =
      scaled >= 100 ? Math.round(scaled) : Number(scaled.toFixed(1));
    return `${rounded}${suffix}`;
  };
  // Enter each unit where the one below would round up to 1000 at its display
  // precision, so a value never shows a four-digit mantissa ("1000K" -> "1M").
  if (abs >= 999.5e6) return format(value / 1e9, "B");
  if (abs >= 999.5e3) return format(value / 1e6, "M");
  if (abs >= 999.95) return format(value / 1e3, "K");
  if (Number.isInteger(value)) return String(value);
  // A small nonzero value must not read as "0.0" beside a delta chip; when one
  // decimal rounds to zero, fall back to two significant figures (0.04, 0.004).
  const oneDecimal = value.toFixed(1);
  return Number.parseFloat(oneDecimal) === 0
    ? `${Number(value.toPrecision(2))}`
    : oneDecimal;
}

export interface ChartHeadlineStat {
  /** Latest value of the series, compact ("17.1K"). */
  value: string;
  /** Change against the previous point; null when too small to show. */
  delta: { label: string; direction: "up" | "down" } | null;
}

/** Changes under this read as noise on a headline, not a trend. */
const MIN_DELTA_PCT = 0.5;

/**
 * Headline for a chart card: the latest value and its step change. Only a
 * single-series chart has one honest headline; anything else returns null.
 */
export function chartHeadlineStat(
  data: ReportChartData,
): ChartHeadlineStat | null {
  // "Latest value and step change" only reads honestly on a single time
  // series; categorical bars have no "latest" and no meaningful step.
  if (
    data.type !== "series" ||
    !data.isTimeSeries ||
    data.series.length !== 1
  ) {
    return null;
  }
  const points = data.series[0].data;
  const last = points[points.length - 1];
  if (typeof last !== "number" || !Number.isFinite(last)) return null;
  const previous = points.length > 1 ? points[points.length - 2] : null;
  let delta: ChartHeadlineStat["delta"] = null;
  if (
    typeof previous === "number" &&
    Number.isFinite(previous) &&
    previous !== 0
  ) {
    const pct = ((last - previous) / Math.abs(previous)) * 100;
    if (Math.abs(pct) >= MIN_DELTA_PCT) {
      const label = `${Math.abs(pct) >= 10 ? Math.round(Math.abs(pct)) : Math.abs(pct).toFixed(1)}%`;
      delta = { label, direction: pct >= 0 ? "up" : "down" };
    }
  }
  return { value: compactChartValue(last), delta };
}

const MAX_SERIES = 15;
const MAX_TABLE_ROWS = 100;
// Past this many categories a bar chart is unreadable; a table serves better.
const MAX_BAR_CATEGORIES = 30;

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

function trendsAggregateValue(result: QueryNode): number | null {
  const aggregated = asFiniteNumber(result.aggregated_value);
  if (aggregated !== null) return aggregated;
  const data = Array.isArray(result.data) ? result.data : [];
  if (data.length === 0) return null;
  return data.reduce<number>(
    (sum, value) => sum + (asFiniteNumber(value) ?? 0),
    0,
  );
}

function trendsAggregateLabel(result: QueryNode, index: number): string {
  // A compared insight returns the current and previous periods as two results
  // with identical labels; the period lives only in compare_label.
  const period =
    typeof result.compare_label === "string" && result.compare_label
      ? ` (${result.compare_label})`
      : "";
  if (Object.hasOwn(result, "breakdown_value")) {
    const value = result.breakdown_value;
    if (value === null || value === undefined || value === "")
      return `No value${period}`;
    if (Array.isArray(value)) return value.map(String).join(" · ") + period;
    return `${String(value)}${period}`;
  }
  const label =
    typeof result.label === "string" && result.label
      ? result.label
      : `Series ${index + 1}`;
  return `${label}${period}`;
}

function shapeTrendsAggregates(
  seriesResults: QueryNode[],
  render: ReportChartRender,
): ReportChartData {
  const entries = seriesResults.flatMap((result, index) => {
    const value = trendsAggregateValue(result);
    return value === null
      ? []
      : [{ label: trendsAggregateLabel(result, index), value }];
  });
  if (entries.length === 0) return { type: "empty" };
  if (render === "number") {
    return {
      type: "number",
      value: entries.reduce((sum, entry) => sum + entry.value, 0),
    };
  }
  if (render === "bar" && entries.length <= MAX_BAR_CATEGORIES) {
    return {
      type: "series",
      render: "bar",
      labels: entries.map((entry) => entry.label),
      series: [
        {
          key: "aggregate-values",
          label: "Total",
          data: entries.map((entry) => entry.value),
        },
      ],
      isTimeSeries: false,
      interval: "day",
    };
  }
  const hasBreakdown = seriesResults.some((result) =>
    Object.hasOwn(result, "breakdown_value"),
  );
  return asTable(
    entries.map((entry) => [entry.label, entry.value]),
    [hasBreakdown ? "Breakdown" : "Series", "Total"],
  );
}

function shapeTrendsResponse(
  response: QueryNode,
  plan: Extract<ReportChartPlan, { kind: "run" }>,
): ReportChartData {
  const results = Array.isArray(response.results) ? response.results : [];
  let seriesResults = results.filter(isRecord);
  // The backend returns all four lifecycle statuses regardless of the saved
  // insight's display filter; the web renderer drops the untoggled ones
  // client-side, so this chart has to as well.
  if (plan.source.kind === "LifecycleQuery") {
    const lifecycleFilter = isRecord(plan.source.lifecycleFilter)
      ? plan.source.lifecycleFilter
      : null;
    const toggled = Array.isArray(lifecycleFilter?.toggledLifecycles)
      ? lifecycleFilter.toggledLifecycles.filter(
          (status): status is string => typeof status === "string",
        )
      : null;
    if (toggled) {
      seriesResults = seriesResults.filter((result) =>
        toggled.includes(String(result.status)),
      );
    }
  }
  if (seriesResults.length === 0) return { type: "empty" };

  if (plan.render === "number" || plan.render === "table") {
    return shapeTrendsAggregates(seriesResults, plan.render);
  }

  const resultsWithData = seriesResults.filter(
    (result) => Array.isArray(result.data) && result.data.length > 0,
  );
  if (resultsWithData.length === 0) {
    return shapeTrendsAggregates(seriesResults, plan.render);
  }

  const first = resultsWithData[0];
  const useStickinessLabels =
    plan.source.kind === "StickinessQuery" && Array.isArray(first.labels);
  const labels = (
    useStickinessLabels
      ? first.labels
      : Array.isArray(first.days)
        ? first.days
        : (first.labels ?? [])
  ) as unknown[];
  const stringLabels = normalizeDayLabels(labels.map(String));
  if (stringLabels.length === 0) {
    return shapeTrendsAggregates(seriesResults, plan.render);
  }

  const series = resultsWithData.slice(0, MAX_SERIES).map((result, index) => ({
    key: `series-${index}`,
    label:
      typeof result.label === "string" && result.label
        ? result.label
        : `Series ${index + 1}`,
    data: (result.data as unknown[]).map((value) => asFiniteNumber(value) ?? 0),
  }));
  return {
    type: "series",
    render: plan.render === "bar" ? "bar" : "line",
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

  const firstColumnDates = rows.every((row) => isDateLike(row[0]));
  const width = rows[0].length;
  const numericTail = (row: unknown[]): boolean =>
    row.slice(1).every((cell) => asFiniteNumber(cell) !== null);

  // Infer the chart for "auto" the way the SQL editor's visualization does:
  // a date-keyed grid is a time series, a short category-keyed grid of
  // numbers is a bar chart, anything else stays a table.
  let effectiveRender = render;
  if (render === "auto" && rows.length >= 2) {
    // A grid wider than MAX_SERIES would lose its extra columns to the series
    // cap below, so keep it a table rather than plot a partial chart, the way
    // pivotBreakdownGrid already falls back for too many breakdowns.
    const chartable =
      (rows.every(numericTail) && width - 1 <= MAX_SERIES) ||
      (width === 3 && firstColumnDates && !numericTail(rows[0]));
    if (chartable && firstColumnDates) {
      effectiveRender = "line";
    } else if (chartable && width >= 2 && rows.length <= MAX_BAR_CATEGORIES) {
      effectiveRender = "bar";
    }
  }

  if (effectiveRender === "line" || effectiveRender === "bar") {
    // A time series has to plot oldest -> newest, but a HogQL result can arrive
    // in any order (ClickHouse GROUP BY with no ORDER BY, or ORDER BY ... DESC).
    // Sort date-keyed rows chronologically so the chart, sparkline, and headline
    // all read the true latest bucket; categorical grids keep the query's order.
    const chartRows = firstColumnDates
      ? [...rows].sort((a, b) => {
          const x = String(a[0]);
          const y = String(b[0]);
          return x < y ? -1 : x > y ? 1 : 0;
        })
      : rows;
    if (width === 3 && firstColumnDates && !numericTail(chartRows[0])) {
      const pivoted = pivotBreakdownGrid(chartRows, columns);
      if (
        pivoted &&
        chartRows.every((row) => asFiniteNumber(row[2]) !== null)
      ) {
        return {
          type: "series",
          render: effectiveRender,
          labels: pivoted.labels,
          series: pivoted.series,
          isTimeSeries: true,
          interval: intervalFor(pivoted.labels),
        };
      }
    }
    if (width >= 2 && chartRows.every(numericTail)) {
      const labels = normalizeDayLabels(chartRows.map((row) => String(row[0])));
      const series = columns.slice(1, 1 + MAX_SERIES).map((column, index) => ({
        key: `column-${index}`,
        label: column || `Series ${index + 1}`,
        data: chartRows.map((row) => asFiniteNumber(row[index + 1]) ?? 0),
      }));
      return {
        type: "series",
        render: effectiveRender,
        labels,
        series,
        isTimeSeries: firstColumnDates,
        interval: intervalFor(labels),
      };
    }
  }

  return asTable(rows, columns);
}

function funnelStepName(step: QueryNode, index: number): string {
  if (typeof step.custom_name === "string" && step.custom_name)
    return step.custom_name;
  if (typeof step.name === "string" && step.name) return step.name;
  return `Step ${index + 1}`;
}

/**
 * A steps funnel becomes a categorical bar chart: one bar per step, one
 * series per breakdown. Results arrive either as a flat step list or, with a
 * breakdown, as one step list per breakdown value.
 */
function shapeFunnelsResponse(response: QueryNode): ReportChartData {
  const results = Array.isArray(response.results) ? response.results : [];
  const branches: QueryNode[][] = results.every(Array.isArray)
    ? (results as unknown[][]).map((branch) => branch.filter(isRecord))
    : [results.filter(isRecord)];
  const steps = branches[0] ?? [];
  if (steps.length === 0) return { type: "empty" };

  const labels = steps.map((step, index) => funnelStepName(step, index));
  const series = branches.slice(0, MAX_SERIES).map((branch, index) => {
    const breakdown = branch[0]?.breakdown_value;
    const label = Array.isArray(breakdown)
      ? breakdown.map(String).join(" · ")
      : breakdown !== undefined && breakdown !== null && breakdown !== ""
        ? String(breakdown)
        : branches.length > 1
          ? `Series ${index + 1}`
          : "Users";
    return {
      key: `funnel-${index}`,
      label,
      data: labels.map((_, step) => asFiniteNumber(branch[step]?.count) ?? 0),
    };
  });
  return {
    type: "series",
    render: "bar",
    labels,
    series,
    isTimeSeries: false,
    interval: "day",
  };
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
    plan.source.kind === "StickinessQuery" ||
    plan.source.kind === "LifecycleQuery"
  ) {
    return shapeTrendsResponse(response, plan);
  }
  if (plan.source.kind === "FunnelsQuery") {
    return shapeFunnelsResponse(response);
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
