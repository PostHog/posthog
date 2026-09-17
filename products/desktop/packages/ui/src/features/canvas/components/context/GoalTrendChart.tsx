import {
  formatNumber,
  type GoalTarget,
} from "@posthog/core/canvas/contextDocument";
import {
  LineChart,
  type LineChartConfig,
  ReferenceLine,
  type Series,
  type TooltipContext,
  useChartLayout,
  useChartTheme,
} from "@posthog/quill-charts";
import type { TrendPeriod } from "@posthog/ui/features/canvas/deriveTrendSql";
import { useGoalPalette } from "@posthog/ui/features/canvas/goalColors";
import type { GoalTrendPoint } from "@posthog/ui/features/canvas/hooks/useGoalMeasure";
import { useCallback, useId, useMemo } from "react";

const BASE_CONFIG: LineChartConfig = {
  hideXAxis: true,
  hideYAxis: true,
  showGrid: false,
  showAxisLines: false,
  showTickMarks: false,
  showCrosshair: true,
  curve: "linear",
  tooltip: { enabled: true, placement: "follow-data" },
  margins: { top: 6, right: 0, bottom: 0, left: 0 },
};

const INVISIBLE = "rgba(0, 0, 0, 0)";

function formatPeriod(label: string, period: TrendPeriod): string {
  const date = new Date(label);
  if (Number.isNaN(date.getTime())) return label;
  if (period === "month") {
    return date.toLocaleDateString(undefined, {
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  const day = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
  return period === "week" ? `Week of ${day}` : day;
}

interface ThresholdAreaProps {
  points: GoalTrendPoint[];
  threshold: number | null;
  goodAbove: boolean;
  red: string;
  green: string;
}

function ThresholdArea({
  points,
  threshold,
  goodAbove,
  red,
  green,
}: ThresholdAreaProps) {
  const { scales, dimensions } = useChartLayout();
  const id = useId();
  const { width, height, plotLeft, plotTop, plotWidth, plotHeight } =
    dimensions;
  const plotBottom = plotTop + plotHeight;

  const paths = useMemo(() => {
    const coords = points
      .map((point) => {
        const x = scales.x(point.label);
        return x === undefined || Number.isNaN(x)
          ? null
          : `${x},${scales.y(point.value)}`;
      })
      .filter((coord): coord is string => coord !== null);
    if (coords.length < 2) return null;
    const [firstX] = coords[0].split(",");
    const [lastX] = coords[coords.length - 1].split(",");
    return {
      line: `M${coords.join(" L")}`,
      area: `M${firstX},${plotBottom} L${coords.join(" L")} L${lastX},${plotBottom} Z`,
    };
  }, [points, scales, plotBottom]);

  if (!paths) return null;
  const splitY =
    threshold === null
      ? null
      : Math.min(plotBottom, Math.max(plotTop, scales.y(threshold)));
  const layers =
    splitY === null
      ? [{ key: "all", color: red, y: plotTop, h: plotHeight }]
      : [
          {
            key: "above",
            color: goodAbove ? green : red,
            y: plotTop,
            h: splitY - plotTop,
          },
          {
            key: "below",
            color: goodAbove ? red : green,
            y: splitY,
            h: plotBottom - splitY,
          },
        ];

  return (
    <svg
      aria-hidden="true"
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width,
        height,
        pointerEvents: "none",
        overflow: "visible",
      }}
    >
      <defs>
        {layers.map((layer) => (
          <linearGradient
            key={layer.key}
            id={`${id}-fill-${layer.key}`}
            x1="0"
            y1={plotTop}
            x2="0"
            y2={plotBottom}
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0" stopColor={layer.color} stopOpacity={0.32} />
            <stop offset="1" stopColor={layer.color} stopOpacity={0} />
          </linearGradient>
        ))}
        {layers.map((layer) => (
          <clipPath key={layer.key} id={`${id}-clip-${layer.key}`}>
            <rect
              x={plotLeft}
              y={layer.y}
              width={plotWidth}
              height={Math.max(0, layer.h)}
            />
          </clipPath>
        ))}
      </defs>
      {layers.map((layer) => (
        <g key={layer.key} clipPath={`url(#${id}-clip-${layer.key})`}>
          <path d={paths.area} fill={`url(#${id}-fill-${layer.key})`} />
          <path
            d={paths.line}
            fill="none"
            stroke={layer.color}
            strokeWidth={1.75}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </g>
      ))}
    </svg>
  );
}

interface GoalTrendChartProps {
  points: GoalTrendPoint[];
  period: TrendPeriod;
  target: GoalTarget | null;
  unit: string;
}

export function GoalTrendChart({
  points,
  period,
  target,
  unit,
}: GoalTrendChartProps) {
  const theme = useChartTheme();
  const palette = useGoalPalette();
  const labels = useMemo(() => points.map((point) => point.label), [points]);
  const series = useMemo<Series[]>(
    () => [
      {
        key: "value",
        label: "Value",
        data: points.map((point) => point.value),
        color: INVISIBLE,
      },
    ],
    [points],
  );
  const config = useMemo<LineChartConfig>(
    () =>
      target
        ? { ...BASE_CONFIG, valueDomain: { include: [target.value] } }
        : BASE_CONFIG,
    [target],
  );
  const tooltip = useCallback(
    (context: TooltipContext) => {
      const value = context.seriesData[0]?.value;
      return (
        <div className="rounded-md border border-border bg-background px-2 py-1 shadow-sm">
          <div className="text-muted-foreground text-xs">
            {formatPeriod(context.label, period)}
          </div>
          <div className="font-medium text-foreground text-xs tabular-nums">
            {value === undefined || Number.isNaN(value)
              ? "–"
              : `${formatNumber(value)}${unit}`}
          </div>
        </div>
      );
    },
    [period, unit],
  );

  return (
    <LineChart
      series={series}
      labels={labels}
      theme={theme}
      config={config}
      tooltip={tooltip}
      className="h-full w-full"
    >
      <ThresholdArea
        points={points}
        threshold={target?.value ?? null}
        goodAbove={target?.direction !== "at_most"}
        red={palette.red}
        green={palette.green}
      />
      {target ? (
        <ReferenceLine
          value={target.value}
          variant="goal"
          style={{ color: palette.muted, stroke: "dashed", width: 1 }}
        />
      ) : null}
    </LineChart>
  );
}
