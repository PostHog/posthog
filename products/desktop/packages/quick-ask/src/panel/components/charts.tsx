import type React from "react";
import { useCallback, useMemo, useState } from "react";

/** A compact chart: series over shared x-axis labels. */
export interface QuickAskChart {
  kind: "line" | "bar";
  title: string;
  labels: string[];
  series: { name: string; points: number[] }[];
}

/** Normalized plot space; the SVG stretches to fill the card. */
const WIDTH = 100;
const HEIGHT = 48;
const TOP_PAD = 5;
const MAX_X_TICKS = 7;
/** Fixed categorical order; one distinct color per renderable series. */
const SERIES_COLORS = [
  "var(--qa-accent)",
  "var(--qa-series-2)",
  "var(--qa-series-3)",
  "var(--qa-series-4)",
  "var(--qa-series-5)",
  "var(--qa-series-6)",
];
/**
 * The palette is the ceiling: past it, series would share colors and become
 * indistinguishable in the plot, tooltip, and legend alike. Extra series are
 * dropped consistently everywhere and the legend states how many.
 */
const MAX_SERIES = SERIES_COLORS.length;

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** "8/14" (the axis short form) reads as "Aug 14" in the tooltip. */
function tooltipLabel(label: string): string {
  const match = label.match(/^(\d{1,2})\/(\d{1,2})$/);
  if (!match) return label;
  const month = MONTHS[Number(match[1]) - 1];
  return month ? `${month} ${Number(match[2])}` : label;
}

/** 87342 -> "87.3K"; keeps small numbers plain. */
function compactValue(value: number): string {
  const abs = Math.abs(value);
  const format = (scaled: number, suffix: string): string => {
    const rounded =
      scaled >= 100 ? Math.round(scaled) : Number(scaled.toFixed(1));
    return `${rounded}${suffix}`;
  };
  if (abs >= 1e9) return format(value / 1e9, "B");
  if (abs >= 1e6) return format(value / 1e6, "M");
  if (abs >= 1e3) return format(value / 1e3, "K");
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** Rounds up to 1/1.5/2/2.5/3/4/5/6/8 × 10^k so gridlines land on round values. */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (factor * magnitude >= value) return factor * magnitude;
  }
  return 10 * magnitude;
}

interface PlotScale {
  lo: number;
  hi: number;
  /** Round values, bottom to top, for gridlines and their labels. */
  ticks: number[];
  x: (index: number, count: number) => number;
  y: (value: number) => number;
}

function buildScale(series: { points: number[] }[]): PlotScale {
  const all = series.flatMap((entry) => entry.points);
  const hi = niceCeil(Math.max(...all));
  const lo = Math.min(0, ...all);
  const range = hi - lo || 1;
  return {
    lo,
    hi,
    ticks: [lo, (lo + hi) / 2, hi],
    x: (index, count) =>
      count > 1 ? (index / (count - 1)) * WIDTH : WIDTH / 2,
    y: (value) => HEIGHT - ((value - lo) / range) * (HEIGHT - TOP_PAD),
  };
}

function Gridlines({ scale }: { scale: PlotScale }): React.JSX.Element {
  return (
    <g>
      {scale.ticks.map((tick) => (
        <line
          key={tick}
          x1={0}
          x2={WIDTH}
          y1={scale.y(tick)}
          y2={scale.y(tick)}
          stroke="rgba(255, 255, 255, 0.07)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </g>
  );
}

function LinePlot({
  chart,
  scale,
}: {
  chart: QuickAskChart;
  scale: PlotScale;
}): React.JSX.Element {
  return (
    <>
      {chart.series.map((series, seriesIndex) => {
        const line = series.points
          .map(
            (point, index) =>
              `${index === 0 ? "M" : "L"}${scale.x(index, series.points.length).toFixed(1)} ${scale.y(point).toFixed(1)}`,
          )
          .join(" ");
        const color = SERIES_COLORS[seriesIndex] ?? SERIES_COLORS[0];
        return (
          <g key={series.name}>
            {seriesIndex === 0 && (
              <path
                className="qa-chart-area"
                d={`${line} L${WIDTH} ${HEIGHT} L0 ${HEIGHT} Z`}
                fill="url(#qa-line-fill)"
              />
            )}
            <path
              className="qa-chart-line"
              d={line}
              pathLength={1}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          </g>
        );
      })}
    </>
  );
}

function BarPlot({
  chart,
  scale,
  hoverIndex,
}: {
  chart: QuickAskChart;
  scale: PlotScale;
  hoverIndex: number | null;
}): React.JSX.Element {
  // Bars draw a single series; Chart renders multi-series data as lines.
  const points = chart.series[0].points;
  const slot = WIDTH / points.length;
  const barWidth = slot * 0.62;
  const baseline = scale.y(Math.max(scale.lo, 0));
  return (
    <>
      {points.map((point, index) => {
        const top = scale.y(point);
        return (
          <rect
            key={`${index}:${point}`}
            className="qa-chart-bar"
            style={{ animationDelay: `${Math.min(index * 24, 300)}ms` }}
            x={(index * slot + (slot - barWidth) / 2).toFixed(1)}
            y={Math.min(top, baseline).toFixed(1)}
            width={barWidth.toFixed(1)}
            height={Math.max(Math.abs(baseline - top), 0.5).toFixed(1)}
            rx={1.2}
            fill="var(--qa-accent)"
            opacity={
              hoverIndex === null ? 0.82 : hoverIndex === index ? 1 : 0.4
            }
          />
        );
      })}
    </>
  );
}

/**
 * Thins x-axis labels to at most MAX_X_TICKS. Spaced backwards from the last
 * label so the newest one always shows and kept labels never sit adjacent.
 */
function tickLabels(labels: string[]): string[] {
  if (labels.length <= MAX_X_TICKS) return labels;
  const step = Math.ceil(labels.length / MAX_X_TICKS);
  return labels.map((label, index) =>
    (labels.length - 1 - index) % step === 0 ? label : "",
  );
}

/** Latest value plus its change from the previous point, for the header. */
function LatestStat({
  chart,
}: {
  chart: QuickAskChart;
}): React.JSX.Element | null {
  const points = chart.series[0].points;
  const last = points[points.length - 1];
  // Empty query results are valid (e.g. a total-value insight has labels but no
  // points); with no last value there is no headline stat to show. Mirrors the
  // shared `chartHeadlineStat` guard so the header does not read `undefined`.
  if (typeof last !== "number" || !Number.isFinite(last)) return null;
  const previous = points.length > 1 ? points[points.length - 2] : null;
  const deltaPct =
    previous != null && previous !== 0
      ? ((last - previous) / Math.abs(previous)) * 100
      : null;
  return (
    <span className="qa-chart-stat">
      <span className="qa-chart-stat-value">{compactValue(last)}</span>
      {deltaPct != null && Math.abs(deltaPct) >= 0.5 && (
        <span
          className={
            deltaPct >= 0
              ? "qa-chart-delta qa-delta-up"
              : "qa-chart-delta qa-delta-down"
          }
        >
          {deltaPct >= 0 ? "▲" : "▼"}
          {Math.abs(deltaPct) >= 10
            ? Math.round(Math.abs(deltaPct))
            : Math.abs(deltaPct).toFixed(1)}
          %
        </span>
      )}
    </span>
  );
}

interface HoverState {
  index: number;
  /** Fraction across the plot, 0..1, for positioning the crosshair/tooltip. */
  frac: number;
}

export function Chart({
  chart: chartProp,
  onOpen,
}: {
  chart: QuickAskChart;
  /** Makes the title a link into PostHog. */
  onOpen?: () => void;
}): React.JSX.Element {
  // BarPlot draws a single series; a multi-series bar would plot the first
  // series while the tooltip and legend list them all. Lines carry every
  // series, so multi-series bar data renders as a line chart instead.
  const chart: QuickAskChart = useMemo(() => {
    const kind =
      chartProp.kind === "bar" && chartProp.series.length > 1
        ? "line"
        : chartProp.kind;
    return {
      ...chartProp,
      kind,
      series: chartProp.series.slice(0, MAX_SERIES),
    };
  }, [chartProp]);
  const omittedSeries = chartProp.series.length - chart.series.length;
  const [hover, setHover] = useState<HoverState | null>(null);
  const scale = useMemo(() => buildScale(chart.series), [chart.series]);
  const pointCount = chart.series[0].points.length;

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>): void => {
      const rect = event.currentTarget.getBoundingClientRect();
      if (rect.width === 0 || pointCount === 0) return;
      const frac = Math.min(
        Math.max((event.clientX - rect.left) / rect.width, 0),
        1,
      );
      const index =
        chart.kind === "bar"
          ? Math.min(Math.floor(frac * pointCount), pointCount - 1)
          : Math.round(frac * (pointCount - 1));
      setHover({
        index,
        frac: pointCount > 1 ? index / (pointCount - 1) : 0.5,
      });
    },
    [chart.kind, pointCount],
  );

  const onPointerLeave = useCallback((): void => setHover(null), []);

  const hoverRows =
    hover === null
      ? []
      : chart.series
          .map((series, seriesIndex) => ({
            name: series.name,
            color: SERIES_COLORS[seriesIndex] ?? SERIES_COLORS[0],
            value: series.points[hover.index],
          }))
          .filter((row) => row.value != null);

  return (
    <div className="qa-chart">
      <div className="qa-chart-header">
        {onOpen ? (
          <button
            type="button"
            className="qa-chart-title qa-chart-title-link"
            onClick={onOpen}
            title="Open in PostHog"
          >
            {chart.title}
          </button>
        ) : (
          <span className="qa-chart-title">{chart.title}</span>
        )}
        <LatestStat chart={chart} />
      </div>

      <div
        className="qa-chart-plot"
        onPointerMove={onPointerMove}
        onPointerLeave={onPointerLeave}
      >
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          className="qa-chart-svg"
          role="img"
          aria-label={chart.kind === "line" ? "Line chart" : "Bar chart"}
        >
          <defs>
            <linearGradient id="qa-line-fill" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--qa-accent)"
                stopOpacity={0.22}
              />
              <stop
                offset="100%"
                stopColor="var(--qa-accent)"
                stopOpacity={0.02}
              />
            </linearGradient>
          </defs>
          <Gridlines scale={scale} />
          {chart.kind === "line" ? (
            <LinePlot chart={chart} scale={scale} />
          ) : (
            <BarPlot
              chart={chart}
              scale={scale}
              hoverIndex={hover?.index ?? null}
            />
          )}
        </svg>

        {/* Round-value tick labels sit over the gridlines, out of the SVG so
            they keep their aspect under preserveAspectRatio="none". */}
        {scale.ticks
          .filter((tick) => tick !== scale.lo)
          .map((tick) => (
            <span
              key={tick}
              className="qa-chart-ytick"
              style={{ top: `${(scale.y(tick) / HEIGHT) * 100}%` }}
            >
              {compactValue(tick)}
            </span>
          ))}

        {hover !== null && (
          <>
            <div
              className="qa-chart-crosshair"
              style={{ left: `${hover.frac * 100}%` }}
            />
            {chart.kind === "line" &&
              chart.series.map((series, seriesIndex) => {
                const value = series.points[hover.index];
                if (value == null) return null;
                return (
                  <div
                    key={series.name}
                    className="qa-chart-hover-dot"
                    style={{
                      left: `${hover.frac * 100}%`,
                      top: `${(scale.y(value) / HEIGHT) * 100}%`,
                      background:
                        SERIES_COLORS[seriesIndex] ?? SERIES_COLORS[0],
                    }}
                  />
                );
              })}
            <div
              className={
                hover.frac > 0.55
                  ? "qa-chart-tip qa-chart-tip-left"
                  : "qa-chart-tip"
              }
              style={{ left: `${hover.frac * 100}%` }}
            >
              {chart.labels[hover.index] != null && (
                <div className="qa-chart-tip-label">
                  {tooltipLabel(chart.labels[hover.index])}
                </div>
              )}
              {hoverRows.map((row) => (
                <div key={row.name} className="qa-chart-tip-row">
                  <span
                    className="qa-chart-dot"
                    style={{ background: row.color }}
                  />
                  <span className="qa-chart-tip-name">{row.name}</span>
                  <span className="qa-chart-tip-value">
                    {compactValue(row.value)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {chart.labels.length > 0 && (
        <div className="qa-chart-labels">
          {tickLabels(chart.labels).map((label, index) => (
            <span key={`${index}:${label}`}>{label}</span>
          ))}
        </div>
      )}

      {chart.series.length > 1 && (
        <div className="qa-chart-legend">
          {chart.series.map((series, seriesIndex) => (
            <span key={series.name} className="qa-chart-legend-item">
              <span
                className="qa-chart-dot"
                style={{
                  background: SERIES_COLORS[seriesIndex] ?? SERIES_COLORS[0],
                }}
              />
              {series.name}
            </span>
          ))}
          {omittedSeries > 0 && (
            <span className="qa-chart-legend-item">
              +{omittedSeries} more in PostHog
            </span>
          )}
        </div>
      )}
    </div>
  );
}
