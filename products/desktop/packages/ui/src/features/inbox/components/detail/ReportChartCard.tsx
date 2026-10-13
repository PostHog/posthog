import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import {
  type ChartHeadlineStat,
  planReportChart,
  type ReportChartData,
  type ReportChartOpenTarget,
  reportChartHeightClass,
  reportChartOpenTarget,
} from "@posthog/core/inbox/reportCharts";
import { cn } from "@posthog/quill";
import {
  BarChart,
  LineChart,
  type Series,
  TimeSeriesBarChart,
  TimeSeriesLineChart,
  useChartTheme,
} from "@posthog/quill-charts";
import { getCloudUrlFromRegion } from "@posthog/shared";
import type { SignalReportChart } from "@posthog/shared/types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useReportChartData } from "@posthog/ui/features/inbox/hooks/useReportChartData";
import { Button } from "@posthog/ui/primitives/Button";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMemo } from "react";

export type ReportChartCardState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "data"; data: ReportChartData }
  | { kind: "link-out" };

export function reportChartAnchorId(chartId: string): string {
  return `report-chart-${chartId}`;
}

function ChartSeriesBody({
  data,
}: {
  data: Extract<ReportChartData, { type: "series" }>;
}) {
  const theme = useChartTheme();
  const series: Series[] = data.series;
  const config = {
    legend: data.series.length > 1 ? { show: true } : undefined,
    ...(data.isTimeSeries
      ? { xAxis: { interval: data.interval, timezone: "UTC" } }
      : {}),
  };
  if (data.isTimeSeries) {
    return data.render === "bar" ? (
      <TimeSeriesBarChart
        series={series}
        labels={data.labels}
        theme={theme}
        config={config}
      />
    ) : (
      <TimeSeriesLineChart
        series={series}
        labels={data.labels}
        theme={theme}
        config={config}
      />
    );
  }
  return data.render === "bar" ? (
    <BarChart
      series={series}
      labels={data.labels}
      theme={theme}
      config={config}
    />
  ) : (
    <LineChart
      series={series}
      labels={data.labels}
      theme={theme}
      config={config}
    />
  );
}

function ChartTableBody({
  data,
}: {
  data: Extract<ReportChartData, { type: "table" }>;
}) {
  return (
    <div className="min-h-0 overflow-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {data.columns.map((column) => (
              <th
                key={column}
                className="sticky top-0 border-(--gray-4) border-b bg-(--color-panel-solid) px-2 py-1 text-left font-medium text-gray-11"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, rowIndex) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows are static query results with no identity
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  // biome-ignore lint/suspicious/noArrayIndexKey: cells are positional
                  key={cellIndex}
                  className="border-(--gray-3) border-b px-2 py-1 text-gray-11 tabular-nums"
                >
                  {cell === null || cell === undefined ? "" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartMessageBody({
  message,
  openTarget,
  onOpenExternal,
}: {
  message: string;
  openTarget: ReportChartOpenTarget | null;
  onOpenExternal: (url: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
      <span className="text-[13px] text-gray-10">{message}</span>
      {openTarget && (
        <Button
          type="button"
          variant="soft"
          color="gray"
          size="1"
          onClick={() => onOpenExternal(openTarget.url)}
        >
          <ArrowSquareOutIcon size={12} />
          {openTarget.label}
        </Button>
      )}
    </div>
  );
}

interface ReportChartCardViewProps {
  chartId: string;
  title: string;
  caption?: string | null;
  heightClass: string;
  state: ReportChartCardState;
  openTarget: ReportChartOpenTarget | null;
  onOpenExternal?: (url: string) => void;
  /** Latest value + step change, shown on the right of the header. */
  stat?: ChartHeadlineStat | null;
}

/** Pure card; the container resolves the query, plan, and open target. */
export function ReportChartCardView({
  chartId,
  title,
  caption,
  heightClass,
  state,
  openTarget,
  onOpenExternal = openExternalUrl,
  stat,
}: ReportChartCardViewProps) {
  const body = (() => {
    switch (state.kind) {
      case "loading":
        return (
          <div className="h-full min-h-24 w-full animate-pulse rounded-(--radius-1) bg-(--gray-3)" />
        );
      case "error":
        return (
          <ChartMessageBody
            message={state.message}
            openTarget={openTarget}
            onOpenExternal={onOpenExternal}
          />
        );
      case "link-out":
        return (
          <ChartMessageBody
            message="This chart can't be shown here yet."
            openTarget={openTarget}
            onOpenExternal={onOpenExternal}
          />
        );
      case "data":
        switch (state.data.type) {
          case "series":
            return <ChartSeriesBody data={state.data} />;
          case "number":
            return (
              <div className="flex items-center justify-center py-4">
                <span className="font-semibold text-3xl text-gray-12 tabular-nums">
                  {state.data.value.toLocaleString()}
                </span>
              </div>
            );
          case "table":
            return <ChartTableBody data={state.data} />;
          case "empty":
            return (
              <ChartMessageBody
                message="The query behind this chart returned no data."
                openTarget={openTarget}
                onOpenExternal={onOpenExternal}
              />
            );
        }
    }
  })();

  const isFixedHeight = state.kind === "data" && state.data.type === "series";

  return (
    <figure
      id={reportChartAnchorId(chartId)}
      className="m-0 flex scroll-mt-4 flex-col gap-2 rounded-(--radius-2) border border-(--gray-4) bg-(--color-panel-solid) p-3"
      data-testid="report-chart"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-words font-semibold text-[14px] text-gray-12">
          {title}
        </span>
        {stat && (
          <span
            className="flex shrink-0 items-baseline gap-1.5"
            data-testid="chart-headline-stat"
          >
            <span className="font-semibold text-[18px] text-gray-12 tabular-nums leading-none">
              {stat.value}
            </span>
            {stat.delta && (
              // The delta carries no metric polarity, so a rise here isn't
              // necessarily good (errors, latency, cost all land in these
              // cards). Stay neutral and let the arrow convey direction alone,
              // matching how the main app leaves an unlabelled change uncolored.
              <span className="font-medium text-(--gray-11) text-[12px] tabular-nums">
                {stat.delta.direction === "up" ? "▲" : "▼"}
                {stat.delta.label}
              </span>
            )}
          </span>
        )}
        {openTarget && (
          <Button
            type="button"
            variant="ghost"
            color="gray"
            size="1"
            aria-label={openTarget.label}
            tooltipContent={openTarget.label}
            className="shrink-0"
            onClick={() => onOpenExternal(openTarget.url)}
          >
            <ArrowSquareOutIcon size={13} />
          </Button>
        )}
      </div>
      <div
        className={cn(
          "flex min-h-0 w-full flex-col",
          heightClass,
          !isFixedHeight && "overflow-y-auto",
        )}
      >
        {body}
      </div>
      {caption && (
        <figcaption className="m-0 text-[12px] text-gray-10">
          {caption}
        </figcaption>
      )}
    </figure>
  );
}

function ReportChartCard({
  reportId,
  chart,
}: {
  reportId: string;
  chart: SignalReportChart;
}) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const plan = useMemo(() => planReportChart(chart.query), [chart.query]);
  const query = useReportChartData(reportId, chart.chart_id, plan);

  const openTarget = useMemo(() => {
    if (!cloudRegion || !projectId) return null;
    return reportChartOpenTarget(chart.query, {
      cloudUrl: getCloudUrlFromRegion(cloudRegion),
      projectId,
    });
  }, [chart.query, cloudRegion, projectId]);

  if (plan.kind === "invalid") {
    return null;
  }

  const state: ReportChartCardState =
    plan.kind !== "run"
      ? { kind: "link-out" }
      : query.isPending
        ? { kind: "loading" }
        : query.isError
          ? {
              kind: "error",
              message:
                "Couldn't run the query behind this chart. Open it in PostHog to investigate.",
            }
          : { kind: "data", data: query.data };

  return (
    <ReportChartCardView
      chartId={chart.chart_id}
      title={chart.title}
      caption={chart.caption}
      heightClass={reportChartHeightClass(
        chart.size,
        state.kind === "data" ? state.data : null,
      )}
      state={state}
      openTarget={openTarget}
    />
  );
}

/** All of a report's charts, rendered after the summary prose. */
export function ReportChartsSection({
  reportId,
  charts,
}: {
  reportId: string;
  charts: SignalReportChart[] | undefined;
}) {
  if (!charts?.length) {
    return null;
  }
  return (
    <div className="flex flex-col gap-3">
      {charts.map((chart) => (
        <ReportChartCard
          key={chart.chart_id}
          reportId={reportId}
          chart={chart}
        />
      ))}
    </div>
  );
}
