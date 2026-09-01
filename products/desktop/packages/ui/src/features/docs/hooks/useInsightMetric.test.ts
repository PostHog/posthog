import { describe, expect, it } from "vitest";
import { formatMetric, headlineNumber } from "./useInsightMetric";

describe("insight metric", () => {
  // Insight results come in several shapes. Reading the wrong field puts a wrong
  // number in a doc, which is worse than showing none, so each shape is pinned.
  it.each([
    {
      name: "aggregate wins",
      results: [{ aggregated_value: 42, count: 7 }],
      expected: 42,
    },
    {
      name: "count when there is no aggregate",
      results: [{ count: 7 }],
      expected: 7,
    },
    {
      name: "last point of a series",
      results: [{ data: [1, 5, 9], label: "signups" }],
      expected: 9,
    },
    { name: "first cell of a table", results: [[12, "a"]], expected: 12 },
    { name: "a bare number", results: [3], expected: 3 },
    {
      name: "no single number",
      results: [{ values: [{ count: 1 }] }],
      expected: null,
    },
    { name: "nothing at all", results: [], expected: null },
    { name: "not a list", results: { count: 1 }, expected: null },
  ])("$name", ({ results, expected }) => {
    expect(headlineNumber(results)).toBe(expected);
  });

  it.each([
    { value: 1234567, expected: "1,234,567" },
    { value: 5.79, expected: "5.8" },
    { value: 61, expected: "61" },
  ])("formats $value", ({ value, expected }) => {
    expect(formatMetric(value)).toBe(expected);
  });
});
