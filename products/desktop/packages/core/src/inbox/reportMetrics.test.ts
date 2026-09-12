import type { SignalReportMetric } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  cardReportMetric,
  formatReportMetricValue,
  mergeReportMetricSnapshots,
  orderedReportMetrics,
  planReportMetricQuery,
  readReportMetricSeries,
  readReportMetricTotal,
  reportMetricSnapshot,
  reportMetricTrend,
} from "./reportMetrics";

function metric(
  overrides: Partial<SignalReportMetric> = {},
): SignalReportMetric {
  return {
    metric_id: "affected",
    title: "Affected users",
    kind: "custom",
    ...overrides,
  };
}

describe("reportMetrics", () => {
  it("picks the affected-users metric for a row ahead of the primary one", () => {
    const primary = metric({ metric_id: "rate", role: "primary" });
    const reach = metric({ metric_id: "reach", kind: "affected_users" });
    expect(cardReportMetric([primary, reach])).toBe(reach);
    expect(cardReportMetric([primary])).toBe(primary);
    expect(cardReportMetric([metric({ role: "supporting" })])).toBeNull();
    expect(cardReportMetric(undefined)).toBeNull();
  });

  it("leads the detail order with the row metric and keeps the rest in place", () => {
    const first = metric({ metric_id: "sessions" });
    const second = metric({ metric_id: "rate", role: "primary" });
    const third = metric({ metric_id: "errors" });
    expect(
      orderedReportMetrics([first, second, third]).map((m) => m.metric_id),
    ).toEqual(["rate", "sessions", "errors"]);
  });

  it("keeps a metric the refresh left out on its saved snapshot", () => {
    const saved = [
      metric({ metric_id: "a", value: 10, value_at: "2026-01-01T00:00:00Z" }),
      metric({ metric_id: "b", value: 3, series: [1, 3] }),
    ];
    const merged = mergeReportMetricSnapshots(saved, [
      metric({ metric_id: "a", value: 42, value_at: "2026-02-01T00:00:00Z" }),
      metric({ metric_id: "b", value: null }),
    ]);
    expect(merged[0]).toMatchObject({
      value: 42,
      value_at: "2026-02-01T00:00:00Z",
    });
    expect(merged[1]).toMatchObject({ value: 3, series: [1, 3] });
  });

  it.each([
    [34, "percentage", null, "34%"],
    [0.345, "percentage_scaled", null, "34.5%"],
    [1500, "duration", "ms", "1.5s"],
    [87342, "count", "users", "87.3K users"],
    [0.4, "number", null, "0.4"],
  ] as const)("formats %s as %s", (value, format, unit, expected) => {
    expect(
      formatReportMetricValue(value, format, unit, { compact: true }),
    ).toBe(expected);
  });

  it("reports a trend only when the last bucket moved enough to mean something", () => {
    expect(reportMetricTrend([100, 112])).toEqual({
      label: "12%",
      direction: "up",
    });
    expect(reportMetricTrend([100, 99.9])).toBeNull();
    expect(reportMetricTrend([0, 5])).toBeNull();
    expect(reportMetricTrend([5])).toBeNull();
  });

  it("treats a null value as unmeasured rather than zero", () => {
    expect(reportMetricSnapshot(metric({ value: null }))).toBeNull();
    expect(reportMetricSnapshot(metric({ value: 0 }))).toMatchObject({
      value: "0",
    });
  });

  it("derives the two executions a live value needs, and refuses anything else", () => {
    const plan = planReportMetricQuery({
      kind: "InsightVizNode",
      source: {
        kind: "TrendsQuery",
        series: [{ kind: "EventsNode", event: "$pageview" }],
        trendsFilter: { display: "ActionsLineGraph", hiddenLegendIndexes: [1] },
      },
    });
    expect(plan?.total.trendsFilter).toMatchObject({ display: "BoldNumber" });
    expect(plan?.series.trendsFilter).toEqual({
      display: "ActionsBar",
      showPercentStackView: false,
    });
    expect(planReportMetricQuery(null)).toBeNull();
    expect(
      planReportMetricQuery({
        kind: "InsightVizNode",
        source: { kind: "FunnelsQuery" },
      }),
    ).toBeNull();
  });

  it("reads the whole-window aggregate, never a sum of buckets", () => {
    const response = { results: [{ aggregated_value: 512, data: [1, 2, 3] }] };
    expect(readReportMetricTotal(response)).toBe(512);
    expect(readReportMetricSeries(response)).toEqual([1, 2, 3]);
    expect(readReportMetricTotal({ results: [{ data: [1, 2] }] })).toBeNull();
    expect(
      readReportMetricSeries({ results: [{ data: [1, "x"] }] }),
    ).toBeNull();
  });
});
