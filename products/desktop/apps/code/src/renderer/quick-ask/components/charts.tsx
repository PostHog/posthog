import type React from "react";
import type { MockChart } from "../mockResponses";

const WIDTH = 100;
const HEIGHT = 40;
const TOP_PAD = 4;

function scale(points: number[]): [number, number][] {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  return points.map((point, index) => [
    (index / (points.length - 1)) * WIDTH,
    HEIGHT - ((point - min) / range) * (HEIGHT - TOP_PAD),
  ]);
}

function LineChart({ points }: { points: number[] }): React.JSX.Element {
  const coords = scale(points);
  const line = coords
    .map(
      ([x, y], index) =>
        `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`,
    )
    .join(" ");
  const [lastX, lastY] = coords[coords.length - 1];
  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      className="qa-chart-svg"
      role="img"
      aria-label="Line chart"
    >
      <path
        d={`${line} L${WIDTH} ${HEIGHT} L0 ${HEIGHT} Z`}
        fill="url(#qa-line-fill)"
      />
      <path
        d={line}
        fill="none"
        stroke="var(--qa-accent)"
        strokeWidth={1.8}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={lastX}
        cy={lastY}
        r={2.4}
        fill="var(--qa-accent)"
        vectorEffect="non-scaling-stroke"
      />
      <defs>
        <linearGradient id="qa-line-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--qa-accent)" stopOpacity={0.28} />
          <stop offset="100%" stopColor="var(--qa-accent)" stopOpacity={0.02} />
        </linearGradient>
      </defs>
    </svg>
  );
}

function BarChart({ points }: { points: number[] }): React.JSX.Element {
  const max = Math.max(...points);
  const min = Math.min(...points);
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
        const barHeight =
          TOP_PAD + ((point - min) / range) * (HEIGHT - TOP_PAD - 4);
        const isLast = index === points.length - 1;
        return (
          <rect
            key={`${index}:${point}`}
            x={(index * slot + (slot - barWidth) / 2).toFixed(1)}
            y={(HEIGHT - barHeight).toFixed(1)}
            width={barWidth.toFixed(1)}
            height={barHeight.toFixed(1)}
            rx={1.2}
            fill="var(--qa-accent)"
            opacity={isLast ? 1 : 0.45}
          />
        );
      })}
    </svg>
  );
}

export function Chart({ chart }: { chart: MockChart }): React.JSX.Element {
  return (
    <div className="qa-chart">
      <div className="qa-chart-header">
        <span>{chart.title}</span>
        <span>{chart.source}</span>
      </div>
      {chart.kind === "line" ? (
        <LineChart points={chart.points} />
      ) : (
        <BarChart points={chart.points} />
      )}
      <div className="qa-chart-labels">
        {chart.labels.map((label, index) => (
          <span key={`${index}:${label}`}>{label}</span>
        ))}
      </div>
    </div>
  );
}
