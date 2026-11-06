import {
  chartHeadlineStat,
  planReportChart,
  type ReportChartData,
  reportChartHeightClass,
  reportChartOpenTarget,
  shapeReportChartData,
} from "@posthog/core/inbox/reportCharts";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type ReportChartCardState,
  ReportChartCardView,
} from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { ChartBlockSpec } from "@posthog/ui/utils/chartBlocks";
import { useMemo } from "react";
import { ReplayBlockCard } from "./ReplayBlockCard";

/**
 * Full-size chart card for a block-display object tag in an agent message
 * (`<insight display="block"/>` or `<hogql display="block">...`). Renders
 * through the same card and quill-charts pipeline as report charts, so agent
 * charts and report charts look and behave identically. Both modes resolve
 * live at render time; the message stores only the reference or the query.
 */

const CHART_ERROR_MESSAGE =
  "Couldn't run the query behind this chart. Open it in PostHog to investigate.";

function useOpenOptions(): { cloudUrl: string; projectId: number } | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  if (!projectId || !cloudRegion) return null;
  return { cloudUrl: getCloudUrlFromRegion(cloudRegion), projectId };
}

function ChartCard({
  blockKey,
  title,
  caption,
  state,
  openTarget,
}: {
  blockKey: string;
  title: string;
  caption?: string;
  state: ReportChartCardState;
  openTarget: ReturnType<typeof reportChartOpenTarget>;
}) {
  const data = state.kind === "data" ? state.data : null;
  return (
    <div className="mb-2">
      <ReportChartCardView
        chartId={blockKey}
        title={title}
        caption={caption}
        heightClass={reportChartHeightClass(null, data)}
        state={state}
        openTarget={openTarget}
        stat={data ? chartHeadlineStat(data) : null}
      />
    </div>
  );
}

function queryState(query: {
  isPending: boolean;
  isError: boolean;
  data: ReportChartData | undefined;
}): ReportChartCardState {
  if (query.isPending) return { kind: "loading" };
  if (query.isError || !query.data)
    return { kind: "error", message: CHART_ERROR_MESSAGE };
  return { kind: "data", data: query.data };
}

function HogqlChartCard({
  spec,
  blockKey,
}: {
  spec: Extract<ChartBlockSpec, { mode: "hogql" }>;
  blockKey: string;
}) {
  const openOptions = useOpenOptions();
  const node = useMemo(
    () => ({
      kind: "DataVisualizationNode",
      source: { kind: "HogQLQuery", query: spec.query },
    }),
    [spec.query],
  );
  const plan = useMemo(() => planReportChart(node), [node]);
  const query = useAuthenticatedQuery<ReportChartData>(
    ["message-chart-block", blockKey],
    async (client) => {
      if (plan.kind !== "run") return { type: "empty" };
      const response = await client.runQuery(plan.source);
      return shapeReportChartData(response, plan);
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );
  return (
    <ChartCard
      blockKey={blockKey}
      title={spec.title ?? "Query result"}
      caption={spec.caption}
      state={queryState(query)}
      openTarget={openOptions ? reportChartOpenTarget(node, openOptions) : null}
    />
  );
}

interface InsightChartResult {
  name: string | null;
  data: ReportChartData | null;
}

function InsightChartCard({
  spec,
  blockKey,
}: {
  spec: Extract<ChartBlockSpec, { mode: "insight" }>;
  blockKey: string;
}) {
  const openOptions = useOpenOptions();
  const query = useAuthenticatedQuery<InsightChartResult | null>(
    ["message-chart-block", blockKey],
    async (client) => {
      const insight = await client.getInsightDefinition(spec.shortId);
      if (!insight) return null;
      const plan = planReportChart(insight.query);
      if (plan.kind !== "run") return { name: insight.name, data: null };
      const response = insight.response ?? (await client.runQuery(plan.source));
      return { name: insight.name, data: shapeReportChartData(response, plan) };
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );

  const state: ReportChartCardState =
    query.isPending || (!query.isError && query.data === undefined)
      ? { kind: "loading" }
      : query.isError
        ? { kind: "error", message: CHART_ERROR_MESSAGE }
        : query.data === null
          ? {
              kind: "error",
              message: `No insight matches "${spec.shortId}" in the current project.`,
            }
          : query.data?.data
            ? { kind: "data", data: query.data.data }
            : { kind: "link-out" };

  return (
    <ChartCard
      blockKey={blockKey}
      title={spec.title ?? query.data?.name ?? "Insight"}
      caption={spec.caption}
      state={state}
      openTarget={
        openOptions
          ? reportChartOpenTarget(
              { kind: "SavedInsightNode", shortId: spec.shortId },
              openOptions,
            )
          : null
      }
    />
  );
}

export function MessageChartCard({
  spec,
  blockKey,
}: {
  spec: ChartBlockSpec;
  /** Stable identity for the block, e.g. a hash of its source. */
  blockKey: string;
}) {
  if (spec.mode === "insight") {
    return <InsightChartCard spec={spec} blockKey={blockKey} />;
  }
  if (spec.mode === "replay") {
    return <ReplayBlockCard spec={spec} />;
  }
  return <HogqlChartCard spec={spec} blockKey={blockKey} />;
}
