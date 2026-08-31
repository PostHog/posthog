import type { SignalReportChartSize } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  chartHeadlineStat,
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

const stickinessNode = (display?: string) => ({
  kind: "InsightVizNode",
  source: {
    kind: "StickinessQuery",
    series: [{ event: "$pageview" }],
    ...(display ? { stickinessFilter: { display } } : {}),
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
    [{ kind: "InsightVizNode", source: { kind: "FunnelsQuery" } }, "run"],
    [
      {
        kind: "InsightVizNode",
        source: {
          kind: "FunnelsQuery",
          funnelsFilter: { funnelVizType: "time_to_convert" },
        },
      },
      "open-only",
    ],
    [
      {
        kind: "InsightVizNode",
        source: {
          kind: "FunnelsQuery",
          funnelsFilter: { funnelVizType: "steps" },
          compareFilter: { compare: true },
        },
      },
      "open-only",
    ],
    [{ kind: "InsightVizNode", source: { kind: "LifecycleQuery" } }, "run"],
    [
      { kind: "InsightVizNode", source: { kind: "RetentionQuery" } },
      "open-only",
    ],
    [trendsNode(), "run"],
    [trendsNode("WorldMap"), "run"],
    [trendsNode("BoxPlot"), "open-only"],
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
    [stickinessNode(), "bar"],
    [trendsNode("ActionsBar"), "bar"],
    [trendsNode("ActionsStackedBar"), "bar"],
    [trendsNode("ActionsLineGraphCumulative"), "line"],
    [trendsNode("ActionsTable"), "table"],
    [trendsNode("WorldMap"), "table"],
    [trendsNode("BoldNumber"), "number"],
    [trendsNode("Metric"), "number"],
    [hogqlNode(), "auto"],
    [hogqlNode({ display: "ActionsLineGraph" }), "line"],
    [hogqlNode({ display: "ActionsBar" }), "bar"],
    [hogqlNode({ display: "BoldNumber" }), "number"],
    [hogqlNode({ display: "ActionsTable" }), "table"],
  ])("planReportChart(%j) picks render %s", (query, render) => {
    expect(runPlan(query).render).toBe(render);
  });

  it("shapes a lifecycle response into bars, keeping negative statuses", () => {
    const data = shapeReportChartData(
      {
        results: [
          {
            label: "new",
            days: ["2026-08-01", "2026-08-02"],
            data: [5, 8],
          },
          {
            label: "dormant",
            days: ["2026-08-01", "2026-08-02"],
            data: [-3, -6],
          },
        ],
      },
      runPlan({
        kind: "InsightVizNode",
        source: { kind: "LifecycleQuery" },
      }),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      labels: ["2026-08-01", "2026-08-02"],
      series: [
        { label: "new", data: [5, 8] },
        { label: "dormant", data: [-3, -6] },
      ],
    });
  });

  it("drops lifecycle statuses the saved insight has toggled off", () => {
    const data = shapeReportChartData(
      {
        results: [
          {
            label: "new",
            status: "new",
            days: ["2026-08-01", "2026-08-02"],
            data: [5, 8],
          },
          {
            label: "dormant",
            status: "dormant",
            days: ["2026-08-01", "2026-08-02"],
            data: [-3, -6],
          },
        ],
      },
      runPlan({
        kind: "InsightVizNode",
        source: {
          kind: "LifecycleQuery",
          lifecycleFilter: { toggledLifecycles: ["new"] },
        },
      }),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      series: [{ label: "new", data: [5, 8] }],
    });
  });

  it("labels compared aggregate rows with their period", () => {
    const data = shapeReportChartData(
      {
        results: [
          {
            label: "Pageviews",
            aggregated_value: 120,
            compare_label: "current",
          },
          {
            label: "Pageviews",
            aggregated_value: 80,
            compare_label: "previous",
          },
        ],
      },
      runPlan(trendsNode("ActionsTable")),
    );
    expect(data).toMatchObject({
      type: "table",
      rows: [
        ["Pageviews (current)", 120],
        ["Pageviews (previous)", 80],
      ],
    });
  });

  it("shapes a steps funnel into one bar per step", () => {
    const data = shapeReportChartData(
      {
        results: [
          { name: "$pageview", order: 0, count: 120 },
          { name: "sign up", custom_name: "Signed up", order: 1, count: 45 },
        ],
      },
      runPlan({ kind: "InsightVizNode", source: { kind: "FunnelsQuery" } }),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      labels: ["$pageview", "Signed up"],
      series: [{ label: "Users", data: [120, 45] }],
    });
  });

  it("shapes a breakdown funnel into one series per breakdown value", () => {
    const data = shapeReportChartData(
      {
        results: [
          [
            { name: "$pageview", count: 80, breakdown_value: ["Chrome"] },
            { name: "sign up", count: 30, breakdown_value: ["Chrome"] },
          ],
          [
            { name: "$pageview", count: 40, breakdown_value: ["Safari"] },
            { name: "sign up", count: 10, breakdown_value: ["Safari"] },
          ],
        ],
      },
      runPlan({ kind: "InsightVizNode", source: { kind: "FunnelsQuery" } }),
    );
    expect(data).toMatchObject({
      type: "series",
      labels: ["$pageview", "sign up"],
      series: [
        { label: "Chrome", data: [80, 30] },
        { label: "Safari", data: [40, 10] },
      ],
    });
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

  it.each([
    [
      "table",
      "ActionsTable",
      {
        type: "table",
        columns: ["Breakdown", "Total"],
        rows: [
          ["true", 2],
          ["No value", 4],
        ],
      },
    ],
    [
      "categorical bar",
      "ActionsBarValue",
      {
        type: "series",
        render: "bar",
        labels: ["true", "No value"],
        series: [{ label: "Total", data: [2, 4] }],
      },
    ],
  ])(
    "keeps aggregate-only Trends results visible as a %s",
    (_name, display, expected) => {
      const data = shapeReportChartData(
        {
          results: [
            {
              label: "$feature_flag_called - true",
              breakdown_value: "true",
              aggregated_value: 2,
              data: [],
              days: ["2026-08-01"],
            },
            {
              label: "$feature_flag_called - None",
              breakdown_value: null,
              aggregated_value: 4,
              data: [],
              days: ["2026-08-01"],
            },
          ],
        },
        runPlan(trendsNode(display)),
      );
      expect(data).toMatchObject(expected);
    },
  );

  it("uses stickiness bucket labels instead of numeric day indexes", () => {
    const data = shapeReportChartData(
      {
        results: [
          {
            label: "$pageview",
            data: [10, 5],
            labels: ["1 day", "2 days"],
            days: [1, 2],
          },
        ],
      },
      runPlan(stickinessNode()),
    );
    expect(data).toMatchObject({
      type: "series",
      render: "bar",
      labels: ["1 day", "2 days"],
      isTimeSeries: false,
    });
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

  it("sorts a descending-date HogQL grid so the headline reads the latest bucket", () => {
    const data = shapeReportChartData(
      {
        columns: ["day", "errors"],
        results: [
          ["2026-08-03", 30],
          ["2026-08-02", 20],
          ["2026-08-01", 10],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsLineGraph" })),
    );
    expect(data).toMatchObject({
      type: "series",
      isTimeSeries: true,
      labels: ["2026-08-01", "2026-08-02", "2026-08-03"],
      series: [{ label: "errors", data: [10, 20, 30] }],
    });
    // The latest bucket is 30 (up from 20), not the first row's 10.
    expect(chartHeadlineStat(data)).toMatchObject({
      value: "30",
      delta: { direction: "up" },
    });
  });

  it("sorts an out-of-order breakdown grid before pivoting", () => {
    const data = shapeReportChartData(
      {
        columns: ["day", "browser", "count"],
        results: [
          ["2026-08-02", "Chrome", 7],
          ["2026-08-01", "Chrome", 5],
          ["2026-08-01", "Safari", 2],
        ],
      },
      runPlan(hogqlNode({ display: "ActionsBar" })),
    );
    expect(data).toMatchObject({
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
      "a date-keyed grid becomes a line chart",
      [
        ["2026-08-08", 4957305],
        ["2026-08-09", 5103586],
      ],
      ["day", "active_users"],
      { type: "series", render: "line", isTimeSeries: true },
    ],
    [
      "a short category-keyed grid becomes a bar chart",
      [
        ["$pageview", 7848625],
        ["$autocapture", 11150213],
      ],
      ["event", "events"],
      { type: "series", render: "bar", isTimeSeries: false },
    ],
    [
      "a date+breakdown grid pivots into a multi-series line",
      [
        ["2026-08-01", "Chrome", 5],
        ["2026-08-02", "Chrome", 7],
      ],
      ["day", "browser", "count"],
      { type: "series", render: "line", isTimeSeries: true },
    ],
    [
      "a single data row stays a table",
      [["granted", 12]],
      ["scope", "count"],
      { type: "table" },
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

  it("auto display: too many categories for a readable bar stays a table", () => {
    const results = Array.from({ length: 31 }, (_, i) => [`cat-${i}`, i]);
    expect(
      shapeReportChartData(
        { columns: ["name", "count"], results },
        runPlan(hogqlNode()),
      ),
    ).toMatchObject({ type: "table" });
  });

  it("auto display: a numeric grid wider than the series cap stays a table", () => {
    // 16 numeric metrics past the date key exceed the 15-series cap; plotting
    // would silently drop columns, so keep the full grid as a table.
    const columns = [
      "day",
      ...Array.from({ length: 16 }, (_, i) => `m${i + 1}`),
    ];
    const results = [
      ["2026-08-01", ...Array.from({ length: 16 }, (_, i) => i)],
      ["2026-08-02", ...Array.from({ length: 16 }, (_, i) => i + 1)],
    ];
    expect(
      shapeReportChartData({ columns, results }, runPlan(hogqlNode())),
    ).toMatchObject({ type: "table", columns });
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

  const headlineSeries = (
    points: number[][],
    isTimeSeries = true,
  ): ReportChartData => ({
    type: "series",
    render: "line",
    labels: points[0].map((_, i) => `d${i}`),
    series: points.map((data, i) => ({ key: `${i}`, label: `s${i}`, data })),
    isTimeSeries,
    interval: "day",
  });

  it("headlines a single series with its latest value and step change", () => {
    expect(chartHeadlineStat(headlineSeries([[69650, 77400, 17100]]))).toEqual({
      value: "17.1K",
      delta: { label: "78%", direction: "down" },
    });
  });

  it.each([
    [0.04, "0.04"],
    [0.004, "0.004"],
    [-0.04, "-0.04"],
    [999.96, "1K"],
    [999999, "1M"],
    [999999999, "1B"],
  ])(
    "keeps a small nonzero headline visible and promotes at the unit boundary (%d -> %s)",
    (last, expected) => {
      expect(chartHeadlineStat(headlineSeries([[last]]))?.value).toBe(expected);
    },
  );

  it.each([
    [
      "a categorical chart has no latest value",
      headlineSeries([[1, 2, 3]], false),
    ],
    [
      "multiple series have no one honest headline",
      headlineSeries([
        [1, 2],
        [3, 4],
      ]),
    ],
    ["empty series", headlineSeries([[]])],
    ["non-series data", { type: "number", value: 5 } as ReportChartData],
  ])("returns no headline for %s", (_name, data) => {
    expect(chartHeadlineStat(data)).toBeNull();
  });

  it("hides a step change too small to read as a trend", () => {
    expect(chartHeadlineStat(headlineSeries([[1000, 1002]]))?.delta).toBeNull();
  });
});
