import { describe, expect, it } from "vitest";
import { deltaTone, formatChartValue, formatMetricDelta } from "./metricFormat";

describe("deltaTone", () => {
  it.each([
    [null, "minimize", "neutral"],
    [0, "minimize", "neutral"],
    [-10, "minimize", "improved"],
    [10, "minimize", "worsened"],
    [10, "maximize", "improved"],
    [-10, "maximize", "worsened"],
  ] as const)("delta %s under %s is %s", (delta, direction, expected) => {
    expect(deltaTone(delta, direction)).toBe(expected);
  });
});

describe("formatMetricDelta", () => {
  it.each([
    [null, "kB", "Baseline"],
    [10.5, "kB", "+10.5 kB"],
    [-3, null, "-3"],
    [2, "%", "+2%"],
  ])("formats %s with unit %s as %s", (delta, unit, expected) => {
    expect(formatMetricDelta(delta, unit)).toBe(expected);
  });
});

describe("formatChartValue", () => {
  it.each([
    [1234.56, "1,235"],
    [999.456, "999.46"],
    [-1500.4, "-1,500"],
  ])("formats %s as %s", (value, expected) => {
    expect(formatChartValue(value)).toBe(expected);
  });
});
