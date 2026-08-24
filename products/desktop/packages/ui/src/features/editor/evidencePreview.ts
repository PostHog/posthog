import type { EvidenceDetailSection } from "@posthog/api-client/evidence-previews";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  type ChartHeadlineStat,
  chartHeadlineStat,
  planReportChart,
  type ReportChartData,
  shapeReportChartData,
} from "@posthog/core/inbox/reportCharts";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";

/**
 * What the evidence hover card shows for a resolved reference. Built lazily
 * when the card mounts: object kinds resolve their live name and status,
 * query-backed kinds (hogql, insight) run their query and reduce the result
 * to a headline and a sparkline.
 */
export interface EvidenceCardData {
  title: string;
  detail?: string;
  /** Lifecycle state as a badge label + tone, kept out of `detail`. */
  status?: {
    label: string;
    tone: "positive" | "neutral" | "caution" | "critical";
  };
  /** Short scannable attributes, e.g. "100% rollout" or "42 clicks". */
  facts?: string[];
  /** Headline numbers for the full page's stat strip; chips use `facts`. */
  stats?: Array<{ label: string; value: string }>;
  /** Latest value + step change when the result is a single time series. */
  headline?: ChartHeadlineStat | null;
  /** Mini chart of the primary series; `labels` carries bucket dates. */
  spark?: { points: number[]; labels?: string[]; render: "line" | "bar" };
  /** A titled multi-series time chart, drawn with hover values on full pages. */
  chart?: {
    title: string;
    labels: string[];
    series: Array<{ label: string; data: number[] }>;
    render: "line" | "bar";
  };
  sections?: EvidenceDetailSection[];
  /** A dashboard's tiles, each resolvable to a live insight chart. */
  tiles?: Array<{ shortId: string; name: string | null }>;
  /** Canonical id when it differs from the cited one (a flag cited by key). */
  resolvedId?: string;
}

const MAX_SPARK_POINTS = 60;

/** Reduce a shaped chart result to the card's headline + sparkline. */
function fromChartData(
  data: ReportChartData,
  fallbackTitle: string,
): EvidenceCardData {
  if (data.type === "number") {
    return { title: data.value.toLocaleString("en-US") };
  }
  if (data.type === "series" && data.series.length > 0) {
    const primary = data.series[0];
    return {
      title: primary.label,
      detail:
        data.series.length > 1
          ? data.series.map((entry) => entry.label).join(" · ")
          : undefined,
      headline: chartHeadlineStat(data),
      spark: {
        points: primary.data.slice(-MAX_SPARK_POINTS),
        render: data.render,
      },
    };
  }
  if (data.type === "table") {
    return {
      title: `${data.rows.length.toLocaleString("en-US")} ${data.rows.length === 1 ? "row" : "rows"}`,
      detail: data.columns.join(", ") || undefined,
    };
  }
  return { title: fallbackTitle };
}

async function hogqlPreview(
  client: PostHogAPIClient,
  query: string,
): Promise<EvidenceCardData> {
  const source = { kind: "HogQLQuery", query };
  const response = await client.runQuery(source);
  const data = shapeReportChartData(response, {
    kind: "run",
    source,
    render: "auto",
  });
  const preview = fromChartData(data, "No result");
  if (data.type === "series" && preview.spark) {
    return {
      ...preview,
      facts: [`${data.labels.length} rows · ${data.series.length + 1} columns`],
    };
  }
  return preview;
}

async function insightPreview(
  client: PostHogAPIClient,
  shortId: string,
): Promise<EvidenceCardData | null> {
  const insight = await client.getInsightDefinition(shortId);
  if (!insight) return null;
  const base: EvidenceCardData = {
    title: insight.name || shortId,
    detail: insight.description || undefined,
  };
  const plan = planReportChart(insight.query);
  if (plan.kind !== "run") return base;
  const response = insight.response ?? (await client.runQuery(plan.source));
  const chart = fromChartData(shapeReportChartData(response, plan), base.title);
  return { ...chart, title: base.title, detail: chart.detail ?? base.detail };
}

/**
 * Resolve the live preview behind an evidence reference. Returns null when
 * there is nothing to show, so the card falls back to its static form.
 */
export async function fetchEvidencePreview(
  client: PostHogAPIClient,
  target: EvidenceLinkTarget,
): Promise<EvidenceCardData | null> {
  if (target.kind === "hogql") {
    return hogqlPreview(client, target.id);
  }
  if (target.kind === "insight") {
    return insightPreview(client, target.id);
  }
  return client.getEvidencePreview(target.kind, target.id);
}
