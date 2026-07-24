import type {
  AutoresearchDirection,
  AutoresearchIteration,
} from "@posthog/core/autoresearch/schemas";
import {
  LineChart,
  ReferenceLine,
  type Series,
  useChartTheme,
} from "@posthog/quill-charts";
import { Text } from "@radix-ui/themes";
import { useMemo } from "react";
import { formatChartValue, withMetricUnit } from "./metricFormat";

interface MetricChartProps {
  iterations: AutoresearchIteration[];
  direction: AutoresearchDirection;
  targetValue: number | null;
  metricName: string;
  unit: string | null;
}

/**
 * Metric value per iteration, shown as a solid line with dots, plus the best
 * frontier (dashed) and the optional target line.
 */
export function MetricChart({
  iterations,
  direction,
  targetValue,
  metricName,
  unit,
}: MetricChartProps) {
  const theme = useChartTheme();
  // Canvas colors must be concrete because CSS variable strings do not paint. The
  // theme's palette is already resolved from CSS variables.
  const valueColor = theme.colors[0] ?? "#1d4aff";
  const bestColor = theme.axisColor ?? "#8b8d98";

  const series: Series[] = useMemo(
    () => [
      {
        key: "value",
        label: "value",
        data: iterations.map((iteration) => iteration.value),
        color: valueColor,
        points: { radius: 3 },
      },
      {
        key: "best",
        label: "best so far",
        data: iterations.map((iteration) => iteration.bestValue),
        color: bestColor,
        stroke: { pattern: [4, 4] },
      },
    ],
    [iterations, valueColor, bestColor],
  );
  const labels = useMemo(
    () => iterations.map((iteration) => String(iteration.index)),
    [iterations],
  );

  if (iterations.length === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-md border border-(--gray-5) bg-(--gray-2)">
        <Text size="1" color="gray">
          The chart fills in as iterations report "{metricName}".
        </Text>
      </div>
    );
  }

  return (
    <figure
      className="m-0"
      role="img"
      aria-label={`${metricName} per iteration (${direction})`}
    >
      {/* flex-col + fixed height: the quill chart sizes its canvas by filling
          a flex-column parent; a plain block collapses it to 0. */}
      <div className="flex h-[240px] w-full flex-col rounded-md border border-(--gray-5) bg-(--gray-2) p-2">
        <LineChart
          series={series}
          labels={labels}
          config={{
            floatBaseline: true,
            showAxisLines: true,
            showCrosshair: true,
            yTickFormatter: (value) =>
              withMetricUnit(formatChartValue(value), unit),
            // Keep a target outside the current scale visible instead of clipping it.
            valueDomain:
              targetValue === null ? undefined : { include: [targetValue] },
          }}
          theme={theme}
          dataAttr="autoresearch-metric-chart"
        >
          {targetValue !== null && (
            <ReferenceLine
              value={targetValue}
              variant="goal"
              label={`target ${withMetricUnit(formatChartValue(targetValue), unit)}`}
              style={{ color: "var(--green-9)" }}
            />
          )}
        </LineChart>
      </div>
      <figcaption className="mt-1 flex items-center gap-3 text-(--gray-10) text-[11px]">
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-[2px] w-4"
            style={{ background: valueColor }}
          />{" "}
          value
        </span>
        <span className="flex items-center gap-1">
          <span
            className="inline-block h-[2px] w-4 border-t border-dashed"
            style={{ borderColor: bestColor }}
          />{" "}
          best so far
        </span>
      </figcaption>
    </figure>
  );
}
