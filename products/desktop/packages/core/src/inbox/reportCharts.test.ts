import { describe, expect, it } from "vitest";
import {
  chartOpenTarget,
  chartRenderPlan,
  mapHogQLGridResults,
  mapTrendsAggregatedValue,
  mapTrendsResults,
  parseChartRef,
  resolveInlineChartIds,
} from "./reportCharts";

describe("reportCharts", () => {
  it.each([
    ["chart:signups-drop", "signups-drop"],
    ["chart:a1_b-2", "a1_b-2"],
    ["chart:", null],
    ["chart:-starts-with-dash", null],
    ["chart:UPPER", null],
    ["https://example.com", null],
    [null, null],
    [undefined, null],
  ])("parseChartRef(%j) → %j", (href, expected) => {
    expect(parseChartRef(href)).toBe(expected);
  });

  it("routes a SavedInsightNode to its insight, path-encoding the short id", () => {
    expect(
      chartOpenTarget({ kind: "SavedInsightNode", shortId: "abc123" }),
    ).toEqual({ path: "/insights/abc123", label: "Open insight" });
    expect(
      chartOpenTarget({ kind: "SavedInsightNode", shortId: "../../settings" }),
    ).toEqual({
      path: "/insights/..%2F..%2Fsettings",
      label: "Open insight",
    });
  });

  it.each([
    [{ kind: "SavedInsightNode" }],
    [{ kind: "SavedInsightNode", shortId: "" }],
    [{ kind: "SavedInsightNode", shortId: 123 }],
    [null],
    ["not-an-object"],
  ])("returns null when there is nowhere to link: %j", (query) => {
    expect(chartOpenTarget(query)).toBeNull();
  });

  it("routes SQL-backed nodes to the SQL editor and others to a new insight", () => {
    const sql = chartOpenTarget({
      kind: "DataVisualizationNode",
      source: { kind: "HogQLQuery", query: "select 1" },
    });
    expect(sql?.label).toBe("Open in SQL editor");
    expect(sql?.path).toMatch(/^\/sql\?open_query=/);

    const viz = chartOpenTarget({
      kind: "InsightVizNode",
      source: { kind: "TrendsQuery" },
    });
    expect(viz?.label).toBe("Open as new insight");
    expect(viz?.path).toMatch(/^\/insights\/new#q=/);
  });

  it("strips embed presentation flags so the insight scene keeps its defaults", () => {
    const target = chartOpenTarget({
      kind: "InsightVizNode",
      embedded: true,
      showHeader: false,
      source: { kind: "TrendsQuery" },
    });
    const decoded = decodeURIComponent(target?.path.split("#q=")[1] ?? "");
    expect(JSON.parse(decoded)).toEqual({
      kind: "InsightVizNode",
      source: { kind: "TrendsQuery" },
    });
  });

  it("drops the control instead of emitting a URL a proxy would refuse", () => {
    expect(
      chartOpenTarget({
        kind: "InsightVizNode",
        source: { kind: "TrendsQuery", padding: "x".repeat(10_000) },
      }),
    ).toBeNull();
  });

  it.each([
    [
      "trends default display → line",
      { kind: "InsightVizNode", source: { kind: "TrendsQuery" } },
      { kind: "trends", display: "line", cumulative: false },
    ],
    [
      "cumulative display → line with client-side accumulation",
      {
        kind: "InsightVizNode",
        source: {
          kind: "TrendsQuery",
          trendsFilter: { display: "ActionsLineGraphCumulative" },
        },
      },
      { kind: "trends", display: "line", cumulative: true },
    ],
    [
      "BoldNumber → number",
      {
        kind: "InsightVizNode",
        source: {
          kind: "TrendsQuery",
          trendsFilter: { display: "BoldNumber" },
        },
      },
      { kind: "trends", display: "number", cumulative: false },
    ],
    [
      "unmappable display → link-only",
      {
        kind: "InsightVizNode",
        source: {
          kind: "TrendsQuery",
          trendsFilter: { display: "ActionsPie" },
        },
      },
      { kind: "link-only" },
    ],
    [
      "funnels → link-only",
      { kind: "InsightVizNode", source: { kind: "FunnelsQuery" } },
      { kind: "link-only" },
    ],
    [
      "SQL viz → sql",
      {
        kind: "DataVisualizationNode",
        source: { kind: "HogQLQuery", query: "select 1" },
      },
      { kind: "sql" },
    ],
    [
      "saved insight → link-only",
      { kind: "SavedInsightNode", shortId: "abc" },
      { kind: "link-only" },
    ],
  ])("chartRenderPlan: %s", (_name, query, expected) => {
    expect(chartRenderPlan(query)).toMatchObject(expected);
  });

  it("maps trends results to series, preferring day labels when aligned", () => {
    const mapped = mapTrendsResults({
      results: [
        {
          label: "signups",
          data: [1, 2, 3],
          labels: ["Mon", "Tue", "Wed"],
          days: ["2026-08-01", "2026-08-02", "2026-08-03"],
        },
        { label: "churns", data: [0, 1, 0] },
      ],
    });
    expect(mapped).toEqual({
      series: [
        { label: "signups", data: [1, 2, 3] },
        { label: "churns", data: [0, 1, 0] },
      ],
      labels: ["Mon", "Tue", "Wed"],
      days: ["2026-08-01", "2026-08-02", "2026-08-03"],
    });
  });

  it("accumulates cumulative trends client-side", () => {
    const mapped = mapTrendsResults(
      { results: [{ label: "signups", data: [1, 2, 3] }] },
      { cumulative: true },
    );
    expect(mapped?.series[0].data).toEqual([1, 3, 6]);
  });

  it.each([
    ["no results", {}],
    ["empty results", { results: [] }],
    ["row without data", { results: [{ label: "x" }] }],
    ["non-numeric data", { results: [{ data: [1, "two", 3] }] }],
    [
      "mismatched series lengths",
      { results: [{ data: [1, 2] }, { data: [1] }] },
    ],
    ["not an object", "nope"],
  ])("trends mapper refuses %s so the card falls back", (_name, response) => {
    expect(mapTrendsResults(response)).toBeNull();
  });

  it("reads the BoldNumber aggregate and refuses anything else", () => {
    expect(
      mapTrendsAggregatedValue({ results: [{ aggregated_value: 42 }] }),
    ).toBe(42);
    expect(mapTrendsAggregatedValue({ results: [{ data: [1] }] })).toBeNull();
    expect(mapTrendsAggregatedValue(null)).toBeNull();
  });

  it("maps a HogQL grid: first column is the x axis, numeric columns are series", () => {
    const mapped = mapHogQLGridResults({
      columns: ["day", "count", "note"],
      results: [
        ["2026-08-01", 5, "a"],
        ["2026-08-02", 7, "b"],
      ],
    });
    expect(mapped).toEqual({
      series: [{ label: "count", data: [5, 7] }],
      labels: ["2026-08-01", "2026-08-02"],
      days: ["2026-08-01", "2026-08-02"],
    });
  });

  it.each([
    ["a single row", { columns: ["day", "n"], results: [["2026-08-01", 1]] }],
    [
      "no numeric column",
      {
        columns: ["day", "s"],
        results: [
          ["a", "x"],
          ["b", "y"],
        ],
      },
    ],
    ["missing columns", { results: [[1, 2]] }],
  ])("grid mapper refuses %s so the card falls back", (_name, response) => {
    expect(mapHogQLGridResults(response)).toBeNull();
  });

  const CHARTS = [
    { chart_id: "signups", title: "Signups", query: {} },
    { chart_id: "churn", title: "Churn", query: {} },
  ];

  it.each([
    [
      "a reference alone in its paragraph",
      "Intro prose.\n\n[Daily signups](chart:signups)\n\nMore prose.",
      ["signups"],
    ],
    [
      "two references sharing a chart-only paragraph",
      "[A](chart:signups)\n[B](chart:churn)",
      ["signups", "churn"],
    ],
    [
      "a reference with a link title",
      '[Daily](chart:signups "note")',
      ["signups"],
    ],
    [
      "a reference inside prose stays a link, not an inline chart",
      "The dip in [signups](chart:signups) is visible below.",
      [],
    ],
    ["a reference to an unknown chart id", "[X](chart:unknown)", []],
    ["no references at all", "Just prose.", []],
  ])("resolves inline chart ids for %s", (_name, summary, expected) => {
    expect([...resolveInlineChartIds(summary, CHARTS)]).toEqual(expected);
  });
});
