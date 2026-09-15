import {
  type ReportMetricTrend,
  reportMetricSnapshot,
} from "@posthog/core/inbox/reportMetrics";
import type { SignalReportMetric } from "@posthog/shared/types";
import type { ReactNode } from "react";

function measuredLabel(measuredAt: string | null): string | null {
  if (!measuredAt) return null;
  const date = new Date(measuredAt);
  return Number.isNaN(date.getTime())
    ? null
    : `Measured ${date.toLocaleString()}`;
}

/**
 * The direction carries no polarity: a rise in errors, latency or cost is not
 * good news. The arrow states which way the last bucket moved and nothing else,
 * so it stays uncoloured.
 */
export function ReportMetricTrendArrow({
  trend,
}: {
  trend: ReportMetricTrend;
}): React.JSX.Element {
  return (
    <span className="font-medium text-[12px] text-gray-10 tabular-nums">
      {trend.direction === "up" ? "▲" : "▼"}
      {trend.label}
    </span>
  );
}

/**
 * A report's row metric, compact enough for a list row: the measured value and
 * how the last bucket moved. Renders nothing when the metric has no snapshot,
 * because a missing measurement is not zero.
 */
export function ReportMetricStat({
  metric,
}: {
  metric: SignalReportMetric | null;
}): ReactNode {
  const snapshot = reportMetricSnapshot(metric, { compact: true });
  if (!metric || !snapshot) return null;

  const tooltip = [
    metric.title,
    metric.caption,
    measuredLabel(snapshot.measuredAt),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <span
      title={tooltip}
      data-testid="report-metric-stat"
      className="flex shrink-0 items-baseline gap-1"
    >
      <span className="font-semibold text-[13px] text-gray-12 tabular-nums">
        {snapshot.value}
      </span>
      {snapshot.trend && <ReportMetricTrendArrow trend={snapshot.trend} />}
    </span>
  );
}
