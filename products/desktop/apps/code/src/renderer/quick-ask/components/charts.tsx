import type { QuickAskChart } from "@posthog/core/quick-ask/quick-ask";
import type React from "react";

const WIDTH = 100;
const HEIGHT = 40;
const TOP_PAD = 4;
const MAX_X_TICKS = 7;
/** First series gets the accent; the rest stay quiet. */
const SERIES_OPACITY = [1, 0.55, 0.3];

function scaleAll(series: { points: number[] }[]): number[][][] {
  const all = series.flatMap((entry) => entry.points);
  const max = Math.max(...all);
  const min = Math.min(...all, 0);
  const range = max - min || 1;
  return series.map((entry) =>
    entry.points.map((point, index) => [
      entry.points.length > 1
        ? (index / (entry.points.length - 1)) * WIDTH
        : WIDTH / 2,
      HEIGHT - ((point - min) / range) * (HEIGHT - TOP_PAD),
    ]),
  );
}

function LineChart({ chart }: { chart: QuickAskChart }): React.JSX.Element {
  const scaled = scaleAll(chart.series);
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className="qa-chart-svg"
      role="img"
      aria-label="Line chart"
    >
      <defs>
        <linearGradient id="qa-line-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--qa-accent)" stopOpacity={0.24} />
          <stop offset="100%" stopColor="var(--qa-accent)" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      {scaled.map((coords, seriesIndex) => {
        const line = coords
          .map(
            ([x, y], index) =>
              `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`,
          )
          .join(" ");
        const [lastX, lastY] = coords[coords.length - 1];
        return (
          <g
            key={chart.series[seriesIndex].name}
            opacity={SERIES_OPACITY[seriesIndex] ?? 0.3}
          >
            {seriesIndex === 0 && (
              <path
                d={`${line} L${WIDTH} ${HEIGHT} L0 ${HEIGHT} Z`}
                fill="url(#qa-line-fill)"
              />
            )}
            <path
              d={line}
              fill="none"
              stroke="var(--qa-accent)"
              strokeWidth={1.8}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            <circle cx={lastX} cy={lastY} r={2.2} fill="var(--qa-accent)" />
          </g>
        );
      })}
    </svg>
  );
}

function BarChart({ chart }: { chart: QuickAskChart }): React.JSX.Element {
  // Bars draw the first series only; extra series read better as lines.
  const points = chart.series[0].points;
  const max = Math.max(...points);
  const min = Math.min(...points, 0);
  const range = max - min || 1;
  const slot = WIDTH / points.length;
  const barWidth = slot * 0.62;
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className="qa-chart-svg"
      role="img"
      aria-label="Bar chart"
    >
      {points.map((point, index) => {
        const barHeight = ((point - min) / range) * (HEIGHT - TOP_PAD);
        return (
          <rect
            key={`${index}:${point}`}
            x={(index * slot + (slot - barWidth) / 2).toFixed(1)}
            y={(HEIGHT - barHeight).toFixed(1)}
            width={barWidth.toFixed(1)}
            height={Math.max(barHeight, 0.5).toFixed(1)}
            rx={1.2}
            fill="var(--qa-accent)"
            opacity={index === points.length - 1 ? 1 : 0.45}
          />
        );
      })}
    </svg>
  );
}

/** Thins x-axis labels to at most MAX_X_TICKS, keeping first and last. */
function tickLabels(labels: string[]): string[] {
  if (labels.length <= MAX_X_TICKS) return labels;
  const step = Math.ceil(labels.length / MAX_X_TICKS);
  return labels.map((label, index) =>
    index % step === 0 || index === labels.length - 1 ? label : "",
  );
}

export function Chart({ chart }: { chart: QuickAskChart }): React.JSX.Element {
  return (
    <div className="qa-chart">
      <div className="qa-chart-header">
        <span>{chart.title}</span>
        <span>via PostHog</span>
      </div>
      {chart.kind === "line" ? (
        <LineChart chart={chart} />
      ) : (
        <BarChart chart={chart} />
      )}
      {chart.labels.length > 0 && (
        <div className="qa-chart-labels">
          {tickLabels(chart.labels).map((label, index) => (
            <span key={`${index}:${label}`}>{label}</span>
          ))}
        </div>
      )}
    </div>
  );
}
