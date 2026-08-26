import type { AutoresearchDirection } from "@posthog/core/autoresearch/schemas";
import { isImprovement } from "@posthog/core/autoresearch/stats";

/**
 * Attach the run's metric unit to an already-formatted value. Percent hugs
 * the number ("42%"); every other unit gets a space ("412 kB"). A null unit
 * (unitless count, or no report carried one yet) leaves the value bare.
 */
export function withMetricUnit(formatted: string, unit: string | null): string {
  if (!unit) return formatted;
  return unit.startsWith("%") ? `${formatted}${unit}` : `${formatted} ${unit}`;
}

/** Full-precision metric value, as shown in stats and iteration tables. */
export const metricNumberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 4,
});

const wholeNumberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});
const fractionalNumberFormat = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

/** Compact metric value for chart axis labels: no fraction past 1000. */
export function formatChartValue(value: number): string {
  return (
    Math.abs(value) >= 1000 ? wholeNumberFormat : fractionalNumberFormat
  ).format(value);
}

/**
 * Whether an iteration's delta moved the metric the right way. Renderers map
 * a tone to their own color space (Radix tokens on screen, fixed hex in the
 * exported report).
 */
export type DeltaTone = "improved" | "worsened" | "neutral";

export function deltaTone(
  delta: number | null,
  direction: AutoresearchDirection,
): DeltaTone {
  if (delta === null || delta === 0) return "neutral";
  return isImprovement(delta, 0, direction) ? "improved" : "worsened";
}

/** Signed delta with unit ("+1.5 kB"); "Baseline" for the first iteration. */
export function formatMetricDelta(
  delta: number | null,
  unit: string | null,
): string {
  if (delta === null) return "Baseline";
  return withMetricUnit(
    `${delta > 0 ? "+" : ""}${metricNumberFormat.format(delta)}`,
    unit,
  );
}
