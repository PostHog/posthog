import { describe, expect, it } from "vitest";
import {
  formatRankingLift,
  formatRankingProbability,
  rankingLiftBarPercent,
} from "./rankingFormat";

describe("rankingFormat", () => {
  it.each([
    [0.04, "0.0x"],
    [2.74, "2.7x"],
    [9.96, "10x"],
    [12.4, "12x"],
  ])("formats a lift of %s as %s", (lift, expected) => {
    expect(formatRankingLift(lift)).toBe(expected);
  });

  it.each([
    [0.0123, "1.2%"],
    [0.0996, "10%"],
    [0.524, "52%"],
  ])("formats a probability of %s as %s", (probability, expected) => {
    expect(formatRankingProbability(probability)).toBe(expected);
  });

  it.each([
    [0, 0],
    [0.1, 0],
    [1, 50],
    [10, 100],
    [40, 100],
  ])("places a lift of %s at %s%% of the bar", (lift, expected) => {
    expect(rankingLiftBarPercent(lift)).toBeCloseTo(expected);
  });
});
