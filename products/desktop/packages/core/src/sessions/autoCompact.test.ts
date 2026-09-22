import { describe, expect, it } from "vitest";
import {
  type AutoCompactInput,
  clampAutoCompactPercent,
  decideAutoCompact,
} from "./autoCompact";

const base: AutoCompactInput = {
  thresholdPercent: 70,
  percentage: 80,
  isCompacting: false,
  isRunning: false,
  armed: true,
};

describe("decideAutoCompact", () => {
  it("compacts once the window passes the threshold at a resting point", () => {
    expect(decideAutoCompact(base)).toEqual({ compact: true, armed: false });
  });

  it.each([
    ["off", { thresholdPercent: null }],
    ["no usage reported yet", { percentage: null }],
    ["under the threshold", { percentage: 40 }],
    ["already compacting", { isCompacting: true }],
    ["mid-turn", { isRunning: true }],
    ["this crossing already fired", { armed: false }],
  ])("does not compact when %s", (_name, patch) => {
    expect(decideAutoCompact({ ...base, ...patch }).compact).toBe(false);
  });

  it("re-arms only after the window drops back under the threshold", () => {
    // Still above the line after firing: stays disarmed, so a compaction that
    // freed nothing cannot loop.
    expect(
      decideAutoCompact({ ...base, armed: false, percentage: 95 }),
    ).toEqual({ compact: false, armed: false });
    expect(
      decideAutoCompact({ ...base, armed: false, percentage: 30 }),
    ).toEqual({ compact: false, armed: true });
  });

  it.each([
    [10, 50],
    [70, 70],
    [200, 90],
    [72.4, 72],
  ])("clampAutoCompactPercent(%s) -> %s", (value, expected) => {
    expect(clampAutoCompactPercent(value)).toBe(expected);
  });
});
