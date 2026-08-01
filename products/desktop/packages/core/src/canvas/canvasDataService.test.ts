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

  it("rejects when the insight can't be found", async () => {
    fetchInsightByShortId.mockRejectedValue(
      new Error('Insight "nope" not found'),
    );

    await expect(
      makeService().loadInsight({ shortId: "nope" }),
    ).rejects.toThrow('Insight "nope" not found');
  });
});
