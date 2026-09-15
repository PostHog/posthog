import type {
  SignalReportMetric,
  SignalReportMetricValueFormat,
} from "@posthog/shared/types";

type QueryNode = Record<string, unknown>;

function isRecord(value: unknown): value is QueryNode {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The metric a list row shows. Mirrors the backend's row-metric choice
 * (`card_metric_id`): the affected-users count when there is one, otherwise
 * the primary observation, so a row and its refresh agree on which metric
 * was measured first.
 */
export function cardReportMetric(
  metrics: readonly SignalReportMetric[] | undefined,
): SignalReportMetric | null {
  if (!metrics?.length) return null;
  return (
    metrics.find((metric) => metric.kind === "affected_users") ??
    metrics.find((metric) => metric.role === "primary") ??
    null
  );
}

/** Metrics in reading order: the row metric leads, the rest keep their authored order. */
export function orderedReportMetrics(
  metrics: readonly SignalReportMetric[] | undefined,
): SignalReportMetric[] {
  if (!metrics?.length) return [];
  const lead = cardReportMetric(metrics);
  if (!lead) return [...metrics];
  return [lead, ...metrics.filter((metric) => metric !== lead)];
}

/**
 * Replace saved snapshots with fresher ones from the refresh endpoint,
 * matching by `metric_id`. A metric the refresh left out keeps what it had,
 * which is how a failed or budget-skipped query degrades.
 */
export function mergeReportMetricSnapshots(
  metrics: readonly SignalReportMetric[] | undefined,
  snapshots: readonly SignalReportMetric[] | undefined,
): SignalReportMetric[] {
  if (!metrics?.length) return [];
  if (!snapshots?.length) return [...metrics];
  const byId = new Map(snapshots.map((metric) => [metric.metric_id, metric]));
  return metrics.map((metric) => {
    const fresh = byId.get(metric.metric_id);
    if (!fresh || fresh.value == null) return metric;
    return {
      ...metric,
      value: fresh.value,
      value_at: fresh.value_at ?? null,
      series: fresh.series ?? null,
    };
  });
}

function roundForDisplay(value: number): string {
  const abs = Math.abs(value);
  if (Number.isInteger(value)) return value.toLocaleString();
  if (abs >= 100) return Math.round(value).toLocaleString();
  if (abs >= 1)
    return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/** 87342 -> "87.3K". Keeps small numbers plain so a row never reads a real value as 0. */
function compactNumber(value: number): string {
  const abs = Math.abs(value);
  const scaled = (divisor: number, suffix: string): string => {
    const next = value / divisor;
    const rounded =
      Math.abs(next) >= 100 ? Math.round(next) : Number(next.toFixed(1));
    return `${rounded}${suffix}`;
  };
  if (abs >= 999.5e6) return scaled(1e9, "B");
  if (abs >= 999.5e3) return scaled(1e6, "M");
  if (abs >= 999.95) return scaled(1e3, "K");
  return roundForDisplay(value);
}

function formatPercent(value: number): string {
  const abs = Math.abs(value);
  const digits = abs >= 100 ? 0 : abs >= 1 ? 1 : 2;
  return `${Number(value.toFixed(digits))}%`;
}

/** A duration in `unit` ("ms" unless the metric says otherwise), read as ms/s/m/h. */
function formatDuration(
  value: number,
  unit: string | null | undefined,
): string {
  const ms = unit === "s" ? value * 1000 : value;
  const abs = Math.abs(ms);
  if (abs < 1000) return `${Math.round(ms)}ms`;
  if (abs < 60_000)
    return `${Number((ms / 1000).toFixed(abs < 10_000 ? 1 : 0))}s`;
  if (abs < 3_600_000) return `${Number((ms / 60_000).toFixed(1))}m`;
  return `${Number((ms / 3_600_000).toFixed(1))}h`;
}

function formatCurrency(
  value: number,
  unit: string | null | undefined,
  compact: boolean,
): string {
  const currency = unit?.trim().toUpperCase();
  if (currency && /^[A-Z]{3}$/.test(currency)) {
    try {
      return value.toLocaleString(undefined, {
        style: "currency",
        currency,
        notation: compact ? "compact" : "standard",
        maximumFractionDigits: Math.abs(value) >= 100 || compact ? 0 : 2,
      });
    } catch {
      // An ISO-shaped code the runtime does not know still formats as a number.
    }
  }
  const formatted = compact ? compactNumber(value) : roundForDisplay(value);
  return currency ? `${formatted} ${currency}` : formatted;
}

export interface FormatReportMetricOptions {
  /** Shorten large numbers ("87.3K") for a row-sized tile. */
  compact?: boolean;
}

export interface ReportMetricValueParts {
  /** The number itself, already formatted. */
  value: string;
  /** A trailing word such as `users`, kept apart so a tile can set it smaller. */
  suffix: string | null;
}

/**
 * The metric's value as a person reads it. `value_format` decides the shape
 * and `unit` the suffix; `kind` stays semantic and never changes formatting.
 */
export function reportMetricValueParts(
  value: number,
  format: SignalReportMetricValueFormat | null | undefined,
  unit: string | null | undefined,
  options: FormatReportMetricOptions = {},
): ReportMetricValueParts {
  if (!Number.isFinite(value)) return { value: "—", suffix: null };
  const compact = options.compact === true;
  switch (format) {
    case "percentage":
      return { value: formatPercent(value), suffix: null };
    case "percentage_scaled":
      return { value: formatPercent(value * 100), suffix: null };
    case "duration":
      return { value: formatDuration(value, unit), suffix: null };
    case "currency":
      return { value: formatCurrency(value, unit, compact), suffix: null };
    default:
      return {
        value: compact ? compactNumber(value) : roundForDisplay(value),
        suffix: unit?.trim() || null,
      };
  }
}

/** The same value as one string, for a surface with no room to split it. */
export function formatReportMetricValue(
  value: number,
  format: SignalReportMetricValueFormat | null | undefined,
  unit: string | null | undefined,
  options: FormatReportMetricOptions = {},
): string {
  const parts = reportMetricValueParts(value, format, unit, options);
  return parts.suffix ? `${parts.value} ${parts.suffix}` : parts.value;
}

/** Changes under this read as noise rather than a trend. */
const MIN_TREND_PCT = 0.5;

export interface ReportMetricTrend {
  /** Size of the change, already formatted ("12%"). */
  label: string;
  direction: "up" | "down";
}

/**
 * Change of the last bucket against the one before it. The metric carries no
 * polarity, so the direction is stated and never coloured good or bad.
 */
export function reportMetricTrend(
  series: readonly number[] | null | undefined,
): ReportMetricTrend | null {
  if (!series || series.length < 2) return null;
  const last = series[series.length - 1];
  const previous = series[series.length - 2];
  if (!Number.isFinite(last) || !Number.isFinite(previous) || previous === 0) {
    return null;
  }
  const pct = ((last - previous) / Math.abs(previous)) * 100;
  if (Math.abs(pct) < MIN_TREND_PCT) return null;
  const magnitude = Math.abs(pct);
  return {
    label: `${magnitude >= 10 ? Math.round(magnitude) : Number(magnitude.toFixed(1))}%`,
    direction: pct >= 0 ? "up" : "down",
  };
}

export interface ReportMetricSnapshotDisplay {
  value: string;
  trend: ReportMetricTrend | null;
  /** When the value was measured, for a tooltip; null when the backend gave no time. */
  measuredAt: string | null;
}

/**
 * What a surface draws from a metric's saved snapshot, or null when there is
 * no snapshot to draw. A null value means "not measured for this viewer", never zero.
 */
export function reportMetricSnapshot(
  metric: SignalReportMetric | null | undefined,
  options: FormatReportMetricOptions = {},
): ReportMetricSnapshotDisplay | null {
  if (!metric || metric.value == null || !Number.isFinite(metric.value)) {
    return null;
  }
  return {
    value: formatReportMetricValue(
      metric.value,
      metric.value_format,
      metric.unit,
      options,
    ),
    trend: reportMetricTrend(metric.series),
    measuredAt: metric.value_at ?? null,
  };
}

export interface ReportMetricQueryPlan {
  /** InsightVizNode source shaped as BoldNumber; its aggregate is the whole-window value. */
  total: QueryNode;
  /** The same source shaped as ActionsBar; its first series holds the buckets. */
  series: QueryNode;
}

function shapedTrendsSource(source: QueryNode, display: string): QueryNode {
  const trendsFilter = isRecord(source.trendsFilter) ? source.trendsFilter : {};
  const shaped: QueryNode = { ...trendsFilter, display };
  if (display === "ActionsBar") {
    shaped.showPercentStackView = false;
    delete shaped.hiddenLegendIndexes;
  }
  return { ...source, trendsFilter: shaped };
}

/**
 * The two executions a live metric value needs, derived from its stored query
 * exactly as the backend refresh derives them, so both warm the same cache
 * entries. Returns null when the stored query is missing, redacted, or not the
 * Trends shape the contract guarantees — the caller then keeps the snapshot.
 */
export function planReportMetricQuery(
  query: unknown,
): ReportMetricQueryPlan | null {
  if (!isRecord(query) || query.kind !== "InsightVizNode") return null;
  const source = isRecord(query.source) ? query.source : null;
  if (!source || source.kind !== "TrendsQuery") return null;
  return {
    total: shapedTrendsSource(source, "BoldNumber"),
    series: shapedTrendsSource(source, "ActionsBar"),
  };
}

function firstSeries(response: unknown): QueryNode | null {
  if (!isRecord(response) || !Array.isArray(response.results)) return null;
  const first = response.results[0];
  return isRecord(first) ? first : null;
}

/** The whole-window aggregate of a BoldNumber execution; never a sum of buckets. */
export function readReportMetricTotal(response: unknown): number | null {
  const series = firstSeries(response);
  const aggregated = series?.aggregated_value;
  return typeof aggregated === "number" && Number.isFinite(aggregated)
    ? aggregated
    : null;
}

/** As many trailing buckets as the backend keeps on a snapshot. */
const MAX_SERIES_POINTS = 14;

/** Trailing buckets of an ActionsBar execution, oldest first. */
export function readReportMetricSeries(response: unknown): number[] | null {
  const series = firstSeries(response);
  if (!Array.isArray(series?.data)) return null;
  const points = series.data
    .slice(-MAX_SERIES_POINTS)
    .map((point) =>
      typeof point === "number" && Number.isFinite(point) ? point : null,
    );
  return points.some((point) => point === null) ? null : (points as number[]);
}
