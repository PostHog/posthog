import {
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

/**
 * Full-size chart card for a `posthog-chart` block in an agent message.
 * Renders through the same card and quill-charts pipeline as report charts,
 * so agent-message charts and report charts look and behave identically.
 */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}/;

function shapeInlineData(
  spec: Extract<ChartBlockSpec, { mode: "data" }>,
): ReportChartData {
  const isTimeSeries =
    spec.labels.length > 0 &&
    spec.labels.every(
      (label) => DATE_ONLY.test(label) || DATE_TIME.test(label),
    );
  return {
    type: "series",
    render: spec.render,
    labels: spec.labels,
    series: spec.series.map((entry, index) => ({
      key: `${index}:${entry.name}`,
      label: entry.name,
      data: entry.points,
    })),
    isTimeSeries,
    interval: spec.labels.some((label) => DATE_TIME.test(label))
      ? "hour"
      : "day",
  };
}

function QueryChartCard({
  spec,
  blockKey,
}: {
  spec: Extract<ChartBlockSpec, { mode: "query" }>;
  blockKey: string;
}) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const plan = useMemo(() => planReportChart(spec.query), [spec.query]);
  const query = useAuthenticatedQuery<ReportChartData>(
    ["message-chart-block", blockKey],
    async (client) => {
      if (plan.kind !== "run") return { type: "empty" };
      const response = await client.runQuery(plan.source);
      return shapeReportChartData(response, plan);
    },
    {
      enabled: plan.kind === "run",
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );

  const openTarget = useMemo(() => {
    if (!cloudRegion || !projectId) return null;
    return reportChartOpenTarget(spec.query, {
      cloudUrl: getCloudUrlFromRegion(cloudRegion),
      projectId,
    });
  }, [spec.query, cloudRegion, projectId]);

  if (plan.kind === "invalid") return null;

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
      chartId={blockKey}
      title={spec.title ?? "Chart"}
      caption={spec.caption}
      heightClass={reportChartHeightClass(
        null,
        state.kind === "data" ? state.data : null,
      )}
      state={state}
      openTarget={openTarget}
    />
  );
}

export function MessageChartCard({
  spec,
  blockKey,
}: {
  spec: ChartBlockSpec;
  /** Stable identity for the block, e.g. a hash of its fence body. */
  blockKey: string;
}) {
  if (spec.mode === "query") {
    return (
      <div className="mb-2">
        <QueryChartCard spec={spec} blockKey={blockKey} />
      </div>
    );
  }
  const data = shapeInlineData(spec);
  return (
    <div className="mb-2">
      <ReportChartCardView
        chartId={blockKey}
        title={spec.title ?? "Chart"}
        caption={spec.caption}
        heightClass={reportChartHeightClass(null, data)}
        state={{ kind: "data", data }}
        openTarget={null}
      />
    </div>
  );
}
