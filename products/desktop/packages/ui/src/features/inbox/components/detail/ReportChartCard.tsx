import { ArrowSquareOutIcon, ChartLineIcon } from "@phosphor-icons/react";
import {
  chartOpenTarget,
  chartRenderPlan,
  mapHogQLGridResults,
  mapTrendsAggregatedValue,
  mapTrendsResults,
  type ReportChartRenderPlan,
  type ReportChartSeriesData,
  resolveInlineChartIds,
} from "@posthog/core/inbox/reportCharts";
import {
  BarChart,
  LineChart,
  type Series,
  useChartTheme,
} from "@posthog/quill-charts";
import type { SignalReport, SignalReportChart } from "@posthog/shared/types";
import { useReportChartData } from "@posthog/ui/features/inbox/hooks/useReportChartData";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { projectPathUrl } from "@posthog/ui/utils/posthogLinks";
import { useMemo } from "react";

const CHART_HEIGHT: Record<string, string> = {
  small: "h-32",
  medium: "h-56",
  large: "h-72",
};

const NUMBER_FORMAT = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2,
});

interface ReportChartCardProps {
  reportId: string;
  chart: SignalReportChart;
}

/**
 * A report chart, rendered natively through quill-charts when its query maps
 * to a trends line/bar, a single number, or a SQL grid; otherwise (and on any
 * query or mapping failure) the card body explains that the chart lives in
 * PostHog, with the header's open link as the way there.
 */
export function ReportChartCard({ reportId, chart }: ReportChartCardProps) {
  const plan = useMemo(() => chartRenderPlan(chart.query), [chart.query]);
  const openUrl = useMemo(() => {
    const target = chartOpenTarget(chart.query);
    return target
      ? { url: projectPathUrl(target.path), label: target.label }
      : null;
  }, [chart.query]);

  return (
    <figure className="m-0 flex flex-col gap-2 rounded-(--radius-2) border border-(--gray-5) bg-(--color-panel-solid) p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ChartLineIcon size={14} className="shrink-0 text-gray-10" />
          <span className="truncate font-medium text-[13px] text-gray-12">
            {chart.title}
          </span>
        </div>
        {openUrl?.url ? (
          <button
            type="button"
            onClick={() => {
              if (openUrl.url) openExternalUrl(openUrl.url);
            }}
            className="flex shrink-0 items-center gap-1 rounded-sm px-1.5 py-1 text-[12px] text-gray-11 transition-colors hover:bg-(--gray-3) hover:text-gray-12"
          >
            {openUrl.label}
            <ArrowSquareOutIcon size={12} />
          </button>
        ) : null}
      </div>

      <ReportChartBody reportId={reportId} chart={chart} plan={plan} />

      {chart.caption ? (
        <figcaption className="text-[12px] text-gray-10 leading-snug">
          {chart.caption}
        </figcaption>
      ) : null}
    </figure>
  );
}

function ReportChartBody({
  reportId,
  chart,
  plan,
}: ReportChartCardProps & { plan: ReportChartRenderPlan }) {
  if (plan.kind === "link-only") {
    return (
      <p className="m-0 text-[12.5px] text-gray-10">
        This chart type renders in PostHog.
      </p>
    );
  }
  return <RunnableChartBody reportId={reportId} chart={chart} plan={plan} />;
}

function RunnableChartBody({
  reportId,
  chart,
  plan,
}: ReportChartCardProps & {
  plan: Exclude<ReportChartRenderPlan, { kind: "link-only" }>;
}) {
  const { data, isLoading, isError } = useReportChartData(
    reportId,
    chart.chart_id,
    plan.source,
  );

  const mapped = useMemo(() => {
    if (data === undefined) return null;
    if (plan.kind === "sql") {
      return { kind: "series" as const, value: mapHogQLGridResults(data) };
    }
    if (plan.display === "number") {
      return { kind: "number" as const, value: mapTrendsAggregatedValue(data) };
    }
    return {
      kind: "series" as const,
      value: mapTrendsResults(data, { cumulative: plan.cumulative }),
    };
  }, [data, plan]);

  const heightClass =
    CHART_HEIGHT[chart.size ?? "medium"] ?? CHART_HEIGHT.medium;

  if (isLoading) {
    return (
      <div
        className={`${heightClass} w-full animate-pulse rounded-(--radius-1) bg-(--gray-3)`}
        aria-hidden
      />
    );
  }

  if (mapped?.kind === "number" && mapped.value !== null) {
    return (
      <div className="py-2 font-semibold text-3xl text-gray-12 tabular-nums">
        {NUMBER_FORMAT.format(mapped.value)}
      </div>
    );
  }

  if (mapped?.kind === "series" && mapped.value) {
    return (
      <SeriesChart
        data={mapped.value}
        display={plan.kind === "trends" ? plan.display : "line"}
        heightClass={heightClass}
        title={chart.title}
      />
    );
  }

  return (
    <p className="m-0 text-[12.5px] text-gray-10">
      {isError
        ? "Couldn't run this chart's query here. Open it in PostHog to see it."
        : "This chart's results don't render here yet. Open it in PostHog to see it."}
    </p>
  );
}

export function SeriesChart({
  data,
  display,
  heightClass,
  title,
}: {
  data: ReportChartSeriesData;
  display: "line" | "bar" | "number";
  heightClass: string;
  title: string;
}) {
  const theme = useChartTheme();
  const series: Series[] = useMemo(
    () =>
      data.series.map((s, index) => ({
        key: s.label || `series-${index}`,
        label: s.label || title,
        data: s.data,
        color: theme.colors[index % theme.colors.length],
      })),
    [data.series, theme.colors, title],
  );

  const config = {
    showAxisLines: true,
    showCrosshair: true,
  };

  return (
    // flex-col + fixed height: the quill chart sizes its canvas by filling a
    // flex-column parent; a plain block collapses it to 0.
    <div className={`flex ${heightClass} w-full flex-col`}>
      {display === "bar" ? (
        <BarChart
          series={series}
          labels={data.labels}
          config={config}
          theme={theme}
        />
      ) : (
        <LineChart
          series={series}
          labels={data.labels}
          config={config}
          theme={theme}
        />
      )}
    </div>
  );
}

/**
 * The charts that were not drawn inline at a summary reference, rendered as a
 * stack after the summary, mirroring the cloud inbox rule that an unreferenced
 * chart still renders below the prose.
 */
export function ReportTrailingCharts({ report }: { report: SignalReport }) {
  const charts = report.charts ?? [];
  const inlineIds = useMemo(
    () => resolveInlineChartIds(report.summary, charts),
    [report.summary, charts],
  );
  const trailing = charts.filter((chart) => !inlineIds.has(chart.chart_id));
  if (trailing.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {trailing.map((chart) => (
        <ReportChartCard
          key={chart.chart_id}
          reportId={report.id}
          chart={chart}
        />
      ))}
    </div>
  );
}
