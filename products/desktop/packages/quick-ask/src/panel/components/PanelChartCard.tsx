import {
  planReportChart,
  type ReportChartData,
  reportChartOpenTarget,
  shapeReportChartData,
} from "@posthog/core/inbox/reportCharts";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { ChartBlockSpec } from "@posthog/ui/utils/chartBlocks";
import type React from "react";
import { useMemo } from "react";
import { Chart, type QuickAskChart } from "./charts";

/**
 * The panel's rendering of a block-display object tag. Data resolves through
 * the same live pipeline as the shared chart card; only the drawing differs:
 * the compact SVG chart sized for a cursor panel.
 */

function useOpenOptions(): { cloudUrl: string; projectId: number } | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  if (!projectId || !cloudRegion) return null;
  return { cloudUrl: getCloudUrlFromRegion(cloudRegion), projectId };
}

function Frame({
  title,
  openUrl,
  children,
}: {
  title: string;
  openUrl: string | null;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="qa-chart">
      <div className="qa-chart-header">
        {openUrl ? (
          <button
            type="button"
            className="qa-chart-title qa-chart-title-link"
            onClick={() => openExternalUrl(openUrl)}
            title="Open in PostHog"
          >
            {title}
          </button>
        ) : (
          <span className="qa-chart-title">{title}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function Skeleton(): React.JSX.Element {
  return (
    <>
      <div className="qa-skeleton qa-skeleton-line-wide" />
      <div className="qa-skeleton qa-skeleton-line" />
    </>
  );
}

function toChart(data: ReportChartData, title: string): QuickAskChart | null {
  if (data.type !== "series" || data.series.length === 0) return null;
  return {
    kind: data.render,
    title,
    labels: data.labels,
    series: data.series.map((series) => ({
      name: series.label,
      points: series.data,
    })),
  };
}

function ChartBody({
  data,
  title,
  openUrl,
}: {
  data: ReportChartData;
  title: string;
  openUrl: string | null;
}): React.JSX.Element {
  const chart = toChart(data, title);
  if (chart) {
    // The compact chart draws its own header with the headline stat.
    return (
      <Chart
        chart={chart}
        onOpen={openUrl ? () => openExternalUrl(openUrl) : undefined}
      />
    );
  }
  if (data.type === "number") {
    return (
      <Frame title={title} openUrl={openUrl}>
        <div className="qa-chart-number">{data.value.toLocaleString()}</div>
      </Frame>
    );
  }
  if (data.type === "table") {
    return (
      <Frame title={title} openUrl={openUrl}>
        <table className="qa-chart-table">
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.slice(0, 8).map((row, rowIndex) => (
              <tr key={`${rowIndex}:${String(row[0])}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${cellIndex}:${String(cell)}`}>{String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Frame>
    );
  }
  return (
    <Frame title={title} openUrl={openUrl}>
      <div className="qa-chart-note">Open in PostHog to see this one.</div>
    </Frame>
  );
}

function openUrlFor(
  node: unknown,
  options: { cloudUrl: string; projectId: number } | null,
): string | null {
  if (!options) return null;
  return reportChartOpenTarget(node, options)?.url ?? null;
}

function HogqlCard({
  spec,
}: {
  spec: Extract<ChartBlockSpec, { mode: "hogql" }>;
}): React.JSX.Element {
  const openOptions = useOpenOptions();
  const node = useMemo(
    () => ({
      kind: "DataVisualizationNode",
      source: { kind: "HogQLQuery", query: spec.query },
    }),
    [spec.query],
  );
  const plan = useMemo(() => planReportChart(node), [node]);
  const title = spec.title ?? "Query result";
  const query = useAuthenticatedQuery<ReportChartData>(
    ["quick-ask-chart", spec.query],
    async (client) => {
      if (plan.kind !== "run") return { type: "empty" };
      const response = await client.runQuery(plan.source);
      return shapeReportChartData(response, plan);
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );
  const openUrl = openUrlFor(node, openOptions);
  if (query.isPending) {
    return (
      <Frame title={title} openUrl={openUrl}>
        <Skeleton />
      </Frame>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Frame title={title} openUrl={openUrl}>
        <div className="qa-chart-note">
          The query behind this chart failed. Open it in PostHog.
        </div>
      </Frame>
    );
  }
  return <ChartBody data={query.data} title={title} openUrl={openUrl} />;
}

function InsightCard({
  spec,
}: {
  spec: Extract<ChartBlockSpec, { mode: "insight" }>;
}): React.JSX.Element {
  const openOptions = useOpenOptions();
  const query = useAuthenticatedQuery<{
    name: string | null;
    data: ReportChartData | null;
  } | null>(
    ["quick-ask-chart-insight", spec.shortId],
    async (client) => {
      const insight = await client.getInsightDefinition(spec.shortId);
      if (!insight) return null;
      const plan = planReportChart(insight.query);
      if (plan.kind !== "run") return { name: insight.name, data: null };
      const response = await client.runQuery(plan.source);
      return { name: insight.name, data: shapeReportChartData(response, plan) };
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );
  const title = spec.title ?? query.data?.name ?? "Insight";
  const openUrl = openUrlFor(
    { kind: "SavedInsightNode", shortId: spec.shortId },
    openOptions,
  );
  if (query.isPending) {
    return (
      <Frame title={title} openUrl={openUrl}>
        <Skeleton />
      </Frame>
    );
  }
  if (query.isError || !query.data?.data) {
    return (
      <Frame title={title} openUrl={openUrl}>
        <div className="qa-chart-note">Open in PostHog to see this one.</div>
      </Frame>
    );
  }
  return <ChartBody data={query.data.data} title={title} openUrl={openUrl} />;
}

export function PanelChartCard({
  spec,
}: {
  spec: ChartBlockSpec;
}): React.JSX.Element | null {
  if (spec.mode === "hogql") return <HogqlCard spec={spec} />;
  if (spec.mode === "insight") return <InsightCard spec={spec} />;
  // Replay cards need the full player surface; the chip already links out.
  return null;
}
