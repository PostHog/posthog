import {
  orderedReportMetrics,
  type ReportMetricTrend,
  type ReportMetricValueParts,
  reportMetricTrend,
  reportMetricValueParts,
} from "@posthog/core/inbox/reportMetrics";
import { cn } from "@posthog/quill";
import type { SignalReportMetric } from "@posthog/shared/types";
import { ReportMetricTrendArrow } from "@posthog/ui/features/inbox/components/utils/ReportMetricStat";
import { useReportMetricValue } from "@posthog/ui/features/inbox/hooks/useReportMetricValue";

export interface ReportMetricTileViewProps {
  title: string;
  /** The formatted value, or null when there is nothing measured to show. */
  value: ReportMetricValueParts | null;
  trend: ReportMetricTrend | null;
  caption?: string | null;
  /** Small line under the value: when it was measured, or why it is stale. */
  note?: string | null;
  /** The report's key observation, drawn larger than the supporting ones. */
  isLead?: boolean;
  /** Waiting on the live query with no snapshot to stand in. */
  isMeasuring?: boolean;
}

/** Pure tile; the container resolves the live value. */
export function ReportMetricTileView({
  title,
  value,
  trend,
  caption,
  note,
  isLead = false,
  isMeasuring = false,
}: ReportMetricTileViewProps): React.JSX.Element {
  return (
    <div
      data-testid="report-metric"
      className="flex min-w-0 flex-col gap-1 rounded-(--radius-2) border border-(--gray-4) bg-(--color-panel-solid) px-3 py-2.5"
    >
      <dt className="truncate text-[12.5px] text-gray-11" title={title}>
        {title}
      </dt>
      <dd className="m-0 flex items-baseline gap-2">
        {value === null ? (
          <span className="text-[14px] text-gray-10">
            {isMeasuring ? "Measuring…" : "Not measured"}
          </span>
        ) : (
          <span
            className={cn(
              "min-w-0 font-semibold text-gray-12 tabular-nums",
              isLead ? "text-[24px]" : "text-[18px]",
            )}
          >
            {value.value}
            {value.suffix && (
              <span className="ml-1 font-normal text-[12.5px] text-gray-11">
                {value.suffix}
              </span>
            )}
          </span>
        )}
        {trend && <ReportMetricTrendArrow trend={trend} />}
      </dd>
      {caption && <p className="m-0 text-[12px] text-gray-10">{caption}</p>}
      {note && <p className="m-0 text-[11.5px] text-gray-9">{note}</p>}
    </div>
  );
}

function measuredAtLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

function ReportMetricTile({
  reportId,
  metric,
  isLead,
}: {
  reportId: string;
  metric: SignalReportMetric;
  isLead: boolean;
}): React.JSX.Element {
  const live = useReportMetricValue(reportId, metric);

  // The live query is the source of truth; the saved snapshot stands in until it
  // answers and stays put when it cannot, so a failed refresh never blanks the
  // report or blocks the rest of it.
  const value = live.data?.value ?? metric.value ?? null;
  const series = live.data?.series ?? metric.series ?? null;
  const measuredAt = live.data ? null : measuredAtLabel(metric.value_at);

  return (
    <ReportMetricTileView
      title={metric.title}
      value={
        value === null
          ? null
          : reportMetricValueParts(value, metric.value_format, metric.unit)
      }
      trend={reportMetricTrend(series)}
      caption={metric.caption}
      note={
        measuredAt &&
        (live.isError
          ? `Couldn't measure this now. Last measured ${measuredAt}.`
          : `Measured ${measuredAt}`)
      }
      isLead={isLead}
      isMeasuring={live.isPending}
    />
  );
}

/**
 * What the report measured, above the prose that explains it: the key
 * observation first, then the supporting numbers.
 */
export function ReportMetricsSection({
  reportId,
  metrics,
}: {
  reportId: string;
  metrics: SignalReportMetric[] | undefined;
}): React.JSX.Element | null {
  const ordered = orderedReportMetrics(metrics);
  if (ordered.length === 0) return null;

  return (
    <div className="@container">
      <dl
        aria-label="Measured impact"
        data-testid="report-metrics"
        className="m-0 grid @2xl:grid-cols-3 @sm:grid-cols-2 grid-cols-1 gap-2"
      >
        {ordered.map((metric, index) => (
          <ReportMetricTile
            key={metric.metric_id}
            reportId={reportId}
            metric={metric}
            isLead={index === 0}
          />
        ))}
      </dl>
    </div>
  );
}
