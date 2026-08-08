import type { SignalReportChartSize } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  planReportChart,
  type ReportChartData,
  type ReportChartPlan,
  renderableReportChartIds,
  reportChartHeightClass,
  reportChartOpenTarget,
  shapeReportChartData,
} from "./reportCharts";

const OPEN_OPTS = { cloudUrl: "https://us.posthog.com", projectId: 2 };

const hogqlNode = (extra: Record<string, unknown> = {}) => ({
  kind: "DataVisualizationNode",
  source: { kind: "HogQLQuery", query: "SELECT 1" },
  ...extra,
});

const trendsNode = (display?: string) => ({
  kind: "InsightVizNode",
  source: {
    kind: "TrendsQuery",
    series: [{ event: "$pageview" }],
    ...(display ? { trendsFilter: { display } } : {}),
  },
});

const runPlan = (query: unknown) => {
  const plan = planReportChart(query);
  if (plan.kind !== "run")
    throw new Error(`expected run plan, got ${plan.kind}`);
  return plan;
};

describe("reportCharts", () => {
  it.each([
    [null, "invalid"],
    ["SELECT 1", "invalid"],
    [{ noKind: true }, "invalid"],
    [{ kind: "SavedInsightNode" }, "invalid"],
    [{ kind: "SavedInsightNode", shortId: 42 }, "invalid"],
    [{ kind: "SavedInsightNode", shortId: "abc123" }, "saved-insight"],
    [{ kind: "InsightVizNode" }, "invalid"],
    [{ kind: "InsightVizNode", source: { kind: "FunnelsQuery" } }, "open-only"],
    [
      { kind: "InsightVizNode", source: { kind: "RetentionQuery" } },
      "open-only",
    ],
    [trendsNode(), "run"],
    [
      { kind: "DataVisualizationNode", source: { kind: "EventsQuery" } },
      "open-only",
    ],
    [hogqlNode(), "run"],
    [{ kind: "HogQuery", code: "return 1" }, "open-only"],
  ] as [unknown, ReportChartPlan["kind"]][])(
    "planReportChart(%j) -> %s",
    (query, expected) => {
      expect(planReportChart(query).kind).toBe(expected);
    },
  );

  it.each([
    [trendsNode(), "line"],
    [trendsNode("ActionsBar"), "bar"],
    [trendsNode("BoldNumber"), "number"],
    [hogqlNode(), "auto"],
    [hogqlNode({ display: "ActionsLineGraph" }), "line"],
    [hogqlNode({ display: "ActionsBar" }), "bar"],
    [hogqlNode({ display: "BoldNumber" }), "number"],
    [hogqlNode({ display: "ActionsTable" }), "auto"],
  ])("planReportChart(%j) picks render %s", (query, render) => {
    expect(runPlan(query).render).toBe(render);
  });

  it("shapes a trends response into a time series", () => {
    const data = shapeReportChartData(
      {
        results: [
          {
            label: "$pageview",
            data: [1, 2, 3],
            days: ["2026-08-01", "2026-08-02", "2026-08-03"],
          },
        ],
      },
      runPlan(trendsNode()),
    );
    expect(data).toEqual({
      type: "series",
      render: "line",
      labels: ["2026-08-01", "2026-08-02", "2026-08-03"],
      series: [{ key: "series-0", label: "$pageview", data: [1, 2, 3] }],
      isTimeSeries: true,
      interval: "day",
    });
  });

  it("sums aggregated values for a BoldNumber trends chart", () => {
    const data = shapeReportChartData(
      { results: [{ aggregated_value: 41 }, { aggregated_value: 1 }] },
      runPlan(trendsNode("BoldNumber")),
    );
    expect(data).toEqual({ type: "number", value: 42 });
  });

  it("normalizes midnight-stamped day buckets to plain dates", () => {
    const data = shapeReportChartData(
      {
        columns: ["day", "errors"],
        results: [
          ["2026-07-26T00:00:00-07:00", 5],
          ["2026-08-01T00:00:00-07:00", 8],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsBar" })),
    );
    expect(data).toMatchObject({
      type: "series",
      isTimeSeries: true,
      interval: "day",
      labels: ["2026-07-26", "2026-08-01"],
    });
  });

  it("shapes a date + numeric HogQL grid into a time series", () => {
    const data = shapeReportChartData(
      {
        columns: ["day", "errors"],
        results: [
          ["2026-08-01", 5],
          ["2026-08-02", 8],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsLineGraph" })),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "line",
      isTimeSeries: true,
      labels: ["2026-08-01", "2026-08-02"],
      series: [{ label: "errors", data: [5, 8] }],
    });
  });

  it("pivots a date + breakdown + value grid into one series per breakdown", () => {
    const data = shapeReportChartData(
      {
        columns: ["day", "browser", "count"],
        results: [
          ["2026-08-01", "Chrome", 5],
          ["2026-08-01", "Safari", 2],
          ["2026-08-02", "Chrome", 7],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsBar" })),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      labels: ["2026-08-01", "2026-08-02"],
      series: [
        { label: "Chrome", data: [5, 7] },
        { label: "Safari", data: [2, 0] },
      ],
    });
  });

  it("keeps a categorical grid as a bar chart with string labels", () => {
    const data = shapeReportChartData(
      {
        columns: ["scope", "count"],
        results: [
          ["granted", 12],
          ["denied", 3],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsBar" })),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      isTimeSeries: false,
      labels: ["granted", "denied"],
    });
  });

  it.each([
    [
      "single numeric cell becomes a number",
      [[42]],
      ["total"],
      { type: "number", value: 42 },
    ],
    [
      "non-numeric grid falls back to a table",
      [["a", "b"]],
      ["x", "y"],
      { type: "table", columns: ["x", "y"], rows: [["a", "b"]] },
    ],
  ])("auto display: %s", (_name, results, columns, expected) => {
    expect(
      shapeReportChartData({ columns, results }, runPlan(hogqlNode())),
    ).toMatchObject(expected);
  });

  it("returns empty for a response with no rows", () => {
    expect(
      shapeReportChartData({ columns: [], results: [] }, runPlan(hogqlNode())),
    ).toEqual({ type: "empty" });
    expect(
      shapeReportChartData({ results: [] }, runPlan(trendsNode())),
    ).toEqual({ type: "empty" });
  });

  const seriesData: ReportChartData = {
    type: "series",
    render: "line",
    labels: ["2026-08-01"],
    series: [{ key: "s0", label: "errors", data: [1] }],
    isTimeSeries: true,
    interval: "day",
  };
  // `size` arrives as stored JSON, so the guard has to survive values outside
  // the declared union.
  const unknownSize = "huge" as unknown as SignalReportChartSize;

  it.each<[string, SignalReportChartSize | null, ReportChartData, string]>([
    ["graphs get a fixed height", null, seriesData, "h-72"],
    ["explicit size wins for graphs", "large", seriesData, "h-[28rem]"],
    ["numbers default small", null, { type: "number", value: 1 }, "max-h-36"],
    [
      "tables get a scroll ceiling",
      null,
      { type: "table", columns: ["x"], rows: [[1]] },
      "max-h-72",
    ],
    ["unknown size falls back", unknownSize, seriesData, "h-72"],
  ])("%s", (_name, size, data, expected) => {
    expect(reportChartHeightClass(size, data)).toBe(expected);
  });

  it("only offers jump targets for charts that will render", () => {
    expect(
      renderableReportChartIds([
        { chart_id: "drawable", query: hogqlNode() },
        { chart_id: "broken", query: { noKind: true } },
        { chart_id: "fallback-card", query: { kind: "HogQuery" } },
      ]),
    ).toEqual(["drawable", "fallback-card"]);
    expect(renderableReportChartIds(undefined)).toEqual([]);
  });

  it("links a saved insight to its insight page", () => {
    expect(
      reportChartOpenTarget(
        { kind: "SavedInsightNode", shortId: "aBc12" },
        OPEN_OPTS,
      ),
    ).toEqual({
      url: "https://us.posthog.com/project/2/insights/aBc12",
      label: "Open insight",
    });
  });

  it("routes HogQL-backed nodes to the SQL editor with embed flags stripped", () => {
    const target = reportChartOpenTarget(
      hogqlNode({ embedded: true, showHeader: false }),
      OPEN_OPTS,
    );
    expect(target?.label).toBe("Open in SQL editor");
    expect(target?.url).toContain("/project/2/sql?open_query=");
    expect(target?.url).not.toContain("embedded");
    expect(target?.url).not.toContain("showHeader");
  });

  it("routes other nodes to a new insight", () => {
    const target = reportChartOpenTarget(trendsNode(), OPEN_OPTS);
    expect(target?.label).toBe("Open as new insight");
    expect(target?.url).toContain("/project/2/insights/new?q=");
  });

  it.each([
    ["no kind", { noKind: true }],
    ["missing shortId", { kind: "SavedInsightNode" }],
    ["URL past the request-line cap", hogqlNode({ padding: "x".repeat(9000) })],
  ])("returns null when there is nowhere to link: %s", (_name, query) => {
    expect(reportChartOpenTarget(query, OPEN_OPTS)).toBeNull();
  });
});
