import { describe, expect, it } from "vitest";

import { playbackRateForTaskDuration } from "./playbackRate";

describe("playbackRateForTaskDuration", () => {
  it.each([
    ["below the fast floor (10s)", 10 * 1000, 3],
    ["at the fast floor (30s)", 30 * 1000, 3],
    ["geometric mid of the fast ramp (60s)", 60 * 1000, Math.sqrt(3)],
    ["normal band start (2min)", 2 * 60 * 1000, 1],
    ["normal band end (4min)", 4 * 60 * 1000, 1],
    [
      "geometric mid of the slow ramp",
      Math.sqrt(4 * 60 * 1000 * (30 * 60 * 1000)),
      Math.sqrt(1 / 3),
    ],
    ["at the slow ceiling (30min)", 30 * 60 * 1000, 1 / 3],
    ["beyond the slow ceiling (2h)", 2 * 60 * 60 * 1000, 1 / 3],
    ["NaN (non-finite) → fast rate", Number.NaN, 3],
  ])("%s → %f", (_label, durationMs, expected) => {
    expect(playbackRateForTaskDuration(durationMs)).toBeCloseTo(expected, 5);
  });

  it("decreases monotonically as duration grows", () => {
    const durations = [
      10 * 1000,
      45 * 1000,
      90 * 1000,
      2 * 60 * 1000,
      4 * 60 * 1000,
      10 * 60 * 1000,
      30 * 60 * 1000,
    ];
    const rates = durations.map(playbackRateForTaskDuration);
    for (let i = 1; i < rates.length; i++) {
      expect(rates[i]).toBeLessThanOrEqual(rates[i - 1]);
    }
  });
});
