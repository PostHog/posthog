import type { RootLogger } from "@posthog/di/logger";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasDataService } from "./canvasDataService";
import type { InsightFetchResult } from "./posthogApi";

// loadInsight reads a saved insight's stored result via posthogApi; stub the
// module so the service never reaches the network.
const fetchInsightByShortId = vi.fn();
vi.mock("./posthogApi", () => ({
  fetchInsightByShortId: (...args: unknown[]) => fetchInsightByShortId(...args),
  runQuery: vi.fn(),
  fetchCurrentUser: vi.fn(),
}));

// A logger whose .scope() yields a no-op warn (the only method the service uses).
const fakeLogger = {
  scope: () => ({ warn: vi.fn() }),
} as unknown as RootLogger;

function makeService() {
  return new CanvasDataService({} as never, fakeLogger);
}

function insight(partial: Partial<InsightFetchResult>): InsightFetchResult {
  return {
    shortId: "abc123",
    queryKind: "TrendsQuery",
    columns: [],
    results: [],
    resolvedVariables: {},
    ...partial,
  };
}

describe("CanvasDataService.loadInsight", () => {
  beforeEach(() => {
    fetchInsightByShortId.mockReset();
  });

  // Both cases exercise the same result-shape coercion keyed off `queryKind`: a
  // trends-style insight returns SERIES OBJECTS (pass through untouched — wrapping
  // them reads every value as 0); a SQL insight returns ROWS (coerce scalars).
  const series = [
    { data: [1, 2, 3], days: ["a", "b", "c"], count: 6, label: "Signups" },
  ];
  it.each([
    {
      name: "trends-style series objects pass through untouched",
      queryKind: "TrendsQuery",
      columns: [],
      results: series,
      expectedColumns: [],
      expectedResults: series,
    },
    {
      name: "SQL scalar rows are coerced to 1-cell arrays",
      queryKind: "HogQLQuery",
      columns: ["count"],
      results: [123, [456]],
      expectedColumns: ["count"],
      expectedResults: [[123], [456]],
    },
  ])(
    "coerces the result shape by insight type: $name",
    async ({
      queryKind,
      columns,
      results,
      expectedColumns,
      expectedResults,
    }) => {
      fetchInsightByShortId.mockResolvedValue(
        insight({ queryKind, columns, results }),
      );

      const result = await makeService().loadInsight({ shortId: "abc123" });

      expect(result.columns).toEqual(expectedColumns);
      expect(result.results).toEqual(expectedResults);
    },
  );

  it("forwards the date-picker window as a filters_override", async () => {
    fetchInsightByShortId.mockResolvedValue(insight({}));

    await makeService().loadInsight({
      shortId: "abc123",
      dateRange: { date_from: "2026-01-01", date_to: "2026-02-01" },
    });

    expect(fetchInsightByShortId).toHaveBeenCalledWith(
      expect.anything(),
      "abc123",
      { dateRange: { date_from: "2026-01-01", date_to: "2026-02-01" } },
    );
  });

  it("forwards SQL variables alongside the date window", async () => {
    fetchInsightByShortId.mockResolvedValue(
      insight({ resolvedVariables: { product: "surveys" } }),
    );

    await makeService().loadInsight({
      shortId: "abc123",
      variables: { product: "surveys" },
    });

    expect(fetchInsightByShortId).toHaveBeenCalledWith(
      expect.anything(),
      "abc123",
      { dateRange: undefined, variables: { product: "surveys" } },
    );
  });

  // The API drops an override whose code_name matches nothing on the insight, and
  // ignores overrides entirely under sharing-token auth — both silently, leaving the
  // insight's own defaults to compute numbers that look real. Rendering another
  // product's revenue as this product's is worse than showing an error, so a
  // variable that didn't land has to reject.
  it.each([
    {
      name: "the insight has no such variable",
      resolvedVariables: { month: "2026-07-01" },
      expectedError: 'has no SQL variable "product"',
    },
    {
      name: "the override was ignored and the saved default came back",
      resolvedVariables: { product: "session_replay" },
      expectedError: "was not applied",
    },
  ])("rejects when $name", async ({ resolvedVariables, expectedError }) => {
    fetchInsightByShortId.mockResolvedValue(insight({ resolvedVariables }));

    await expect(
      makeService().loadInsight({
        shortId: "abc123",
        variables: { product: "surveys" },
      }),
    ).rejects.toThrow(expectedError);
  });

  it("accepts a non-string variable value the server echoes back", async () => {
    fetchInsightByShortId.mockResolvedValue(
      insight({ resolvedVariables: { threshold: 500, tiers: ["a", "b"] } }),
    );

    await expect(
      makeService().loadInsight({
        shortId: "abc123",
        variables: { threshold: 500, tiers: ["a", "b"] },
      }),
    ).resolves.toBeDefined();
  });

  it("rejects when the insight can't be found", async () => {
    fetchInsightByShortId.mockRejectedValue(
      new Error('Insight "nope" not found'),
    );

    await expect(
      makeService().loadInsight({ shortId: "nope" }),
    ).rejects.toThrow('Insight "nope" not found');
  });

  it("rejects oversized insight results", async () => {
    fetchInsightByShortId.mockResolvedValue(
      insight({ results: Array.from({ length: 1_001 }, () => [1]) }),
    );

    await expect(
      makeService().loadInsight({ shortId: "too-large" }),
    ).rejects.toThrow("result limit");
  });
});
