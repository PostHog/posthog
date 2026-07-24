import type { SignalReport, SignalReportPriority } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  buildArchiveListOrdering,
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  buildSuggestedReviewerFilterParam,
  filterReportsBySearch,
} from "./reportFiltering";

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "1",
    title: "Test report",
    summary: "A summary of the report",
    status: "ready",
    total_weight: 50,
    signal_count: 10,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-02T00:00:00Z",
    artefact_count: 3,
    ...overrides,
  };
}

describe("filterReportsBySearch", () => {
  const reports = [
    makeReport({
      id: "1",
      title: "Login errors spike",
      summary: "Users cannot log in",
    }),
    makeReport({
      id: "2",
      title: "Checkout flow broken",
      summary: "Payment page crashes",
    }),
    makeReport({
      id: "3",
      title: "Slow dashboard load",
      summary: "Performance degradation",
    }),
  ];

  it("returns all reports when query is empty", () => {
    expect(filterReportsBySearch(reports, "")).toEqual(reports);
  });

  it("returns all reports when query is whitespace", () => {
    expect(filterReportsBySearch(reports, "   ")).toEqual(reports);
  });

  it("filters by title match", () => {
    const result = filterReportsBySearch(reports, "login");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("1");
  });

  it("filters by summary match", () => {
    const result = filterReportsBySearch(reports, "payment");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("2");
  });

  it("is case insensitive", () => {
    const result = filterReportsBySearch(reports, "DASHBOARD");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("3");
  });

  it("handles null title", () => {
    const withNull = [
      makeReport({ id: "4", title: null, summary: "Some summary" }),
    ];
    const result = filterReportsBySearch(withNull, "some");
    expect(result).toHaveLength(1);
  });

  it("handles null summary", () => {
    const withNull = [makeReport({ id: "5", title: "A title", summary: null })];
    const result = filterReportsBySearch(withNull, "title");
    expect(result).toHaveLength(1);
  });

  it("handles both null title and summary", () => {
    const withNull = [makeReport({ id: "6", title: null, summary: null })];
    const result = filterReportsBySearch(withNull, "anything");
    expect(result).toHaveLength(0);
  });

  it("returns empty array when no matches", () => {
    const result = filterReportsBySearch(reports, "nonexistent");
    expect(result).toHaveLength(0);
  });

  it("returns empty array for empty input", () => {
    expect(filterReportsBySearch([], "test")).toEqual([]);
  });
});

describe("buildSignalReportListOrdering", () => {
  it.each([
    ["total_weight", "desc", "status,-total_weight,priority"],
    ["created_at", "asc", "status,created_at,priority"],
    ["signal_count", "desc", "status,-signal_count,priority"],
  ] as const)(
    "orders by status then %s (%s), tiebreaking by priority",
    (field, direction, expected) => {
      expect(buildSignalReportListOrdering(field, direction)).toBe(expected);
    },
  );

  it.each([
    ["priority", "asc", "status,priority,-created_at"],
    ["priority", "desc", "status,-priority,-created_at"],
  ] as const)(
    "tiebreaks %s (%s) by newest first",
    (field, direction, expected) => {
      expect(buildSignalReportListOrdering(field, direction)).toBe(expected);
    },
  );

  it("does not float the current user's reports via ordering", () => {
    expect(buildSignalReportListOrdering("priority", "asc")).not.toContain(
      "is_suggested_reviewer",
    );
  });
});

describe("buildArchiveListOrdering", () => {
  it.each([
    ["updated_at", "desc", "-updated_at"],
    ["updated_at", "asc", "updated_at"],
    ["created_at", "desc", "-created_at"],
  ] as const)("orders by %s (%s) only", (field, direction, expected) => {
    expect(buildArchiveListOrdering(field, direction)).toBe(expected);
  });

  it("does not prefix with status, so suppressed and resolved interleave by time", () => {
    expect(buildArchiveListOrdering("updated_at", "desc")).not.toContain(
      "status",
    );
  });
});

describe("buildSuggestedReviewerFilterParam", () => {
  it("returns undefined for an empty array", () => {
    expect(buildSuggestedReviewerFilterParam([])).toBeUndefined();
  });

  it("trims reviewer ids and joins them with commas", () => {
    expect(
      buildSuggestedReviewerFilterParam([
        " reviewer-1 ",
        "reviewer-2",
        " reviewer-3",
      ]),
    ).toBe("reviewer-1,reviewer-2,reviewer-3");
  });

  it("deduplicates reviewer ids after trimming", () => {
    expect(
      buildSuggestedReviewerFilterParam([
        " reviewer-1 ",
        "reviewer-2",
        "reviewer-1",
        " reviewer-2 ",
      ]),
    ).toBe("reviewer-1,reviewer-2");
  });

  it("drops blank reviewer ids", () => {
    expect(
      buildSuggestedReviewerFilterParam([
        "reviewer-1",
        "   ",
        "reviewer-2",
        "",
      ]),
    ).toBe("reviewer-1,reviewer-2");
  });
});

describe("buildPriorityFilterParam", () => {
  it.each([
    { input: [] as SignalReportPriority[], expected: undefined },
    {
      input: ["P0", "P1", "P2"] as SignalReportPriority[],
      expected: "P0,P1,P2",
    },
    {
      input: ["P0", "P1", "P0", "P2", "P1"] as SignalReportPriority[],
      expected: "P0,P1,P2",
    },
  ])("buildPriorityFilterParam($input) → $expected", ({ input, expected }) => {
    expect(buildPriorityFilterParam(input)).toBe(expected);
  });
});
