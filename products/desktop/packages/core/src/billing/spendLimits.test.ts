import { describe, expect, it } from "vitest";
import {
  EMPTY_SPEND_LIMITS,
  evaluateSpendLimits,
  maskStops,
  parseSpendAmount,
  projectedMonthUsd,
  pruneSpendNoticesSeen,
  type SpendLimits,
  type SpendLimitsPatch,
  spendLimitNoticeKey,
  spendTickIncrement,
  spendTotalsFromDays,
  suggestedSpendLimits,
} from "./spendLimits";

const TODAY = "2026-08-22";

function limits(patch: SpendLimitsPatch): SpendLimits {
  return {
    day: { ...EMPTY_SPEND_LIMITS.day, ...patch.day },
    month: { ...EMPTY_SPEND_LIMITS.month, ...patch.month },
  };
}

describe("spendLimits", () => {
  it("splits today's spend from the month's and excludes other months", () => {
    const totals = spendTotalsFromDays(
      [
        { day: "2026-07-31", cost_usd: 100 },
        { day: "2026-08-01", cost_usd: 3 },
        { day: "2026-08-22", cost_usd: 7 },
      ],
      TODAY,
    );
    expect(totals).toEqual({ todayUsd: 7, monthUsd: 10 });
  });

  it.each<{
    name: string;
    limits: SpendLimitsPatch;
    totals: { todayUsd: number; monthUsd: number };
    expected: { period: string; level: string; limitUsd: number }[];
  }>([
    {
      name: "no lines set never crosses",
      limits: {},
      totals: { todayUsd: 999, monthUsd: 999 },
      expected: [],
    },
    {
      name: "spend below the line does not cross",
      limits: { day: { warnUsd: 20 } },
      totals: { todayUsd: 19.99, monthUsd: 19.99 },
      expected: [],
    },
    {
      name: "spend exactly on the line crosses",
      limits: { day: { warnUsd: 20 } },
      totals: { todayUsd: 20, monthUsd: 20 },
      expected: [{ period: "day", level: "warn", limitUsd: 20 }],
    },
    {
      name: "stop supersedes warn for the same period",
      limits: { day: { warnUsd: 20, stopUsd: 50 } },
      totals: { todayUsd: 60, monthUsd: 60 },
      expected: [{ period: "day", level: "stop", limitUsd: 50 }],
    },
    {
      name: "daily and monthly cross independently, daily first",
      limits: { day: { warnUsd: 20 }, month: { stopUsd: 200 } },
      totals: { todayUsd: 25, monthUsd: 250 },
      expected: [
        { period: "day", level: "warn", limitUsd: 20 },
        { period: "month", level: "stop", limitUsd: 200 },
      ],
    },
    {
      name: "a zero line is treated as off",
      limits: { day: { warnUsd: 0 } },
      totals: { todayUsd: 5, monthUsd: 5 },
      expected: [],
    },
  ])("$name", ({ limits: patch, totals, expected }) => {
    const crossings = evaluateSpendLimits(limits(patch), totals, TODAY);
    expect(
      crossings.map(({ period, level, limitUsd }) => ({
        period,
        level,
        limitUsd,
      })),
    ).toEqual(expected);
  });

  it("keys notices by period, level, anchor, and amount", () => {
    const key = spendLimitNoticeKey({
      period: "day",
      level: "stop",
      limitUsd: 50,
      spentUsd: 61,
      anchor: TODAY,
    });
    expect(key).toBe("day:stop:2026-08-22:50");
  });

  it("re-arms a raised line within the same day via a distinct key", () => {
    const at20 = evaluateSpendLimits(
      limits({ day: { warnUsd: 20 } }),
      { todayUsd: 30, monthUsd: 30 },
      TODAY,
    )[0];
    const at25 = evaluateSpendLimits(
      limits({ day: { warnUsd: 25 } }),
      { todayUsd: 30, monthUsd: 30 },
      TODAY,
    )[0];
    expect(spendLimitNoticeKey(at20)).not.toBe(spendLimitNoticeKey(at25));
  });

  it("prunes seen notices from past months but keeps this month's", () => {
    const pruned = pruneSpendNoticesSeen(
      {
        "day:warn:2026-07-30:20": "2026-07-30",
        "month:warn:2026-07:200": "2026-07",
        "day:stop:2026-08-22:50": "2026-08-22",
        "month:stop:2026-08:200": "2026-08",
      },
      TODAY,
    );
    expect(Object.keys(pruned).sort()).toEqual([
      "day:stop:2026-08-22:50",
      "month:stop:2026-08:200",
    ]);
  });

  it("projects the month from the daily average and the month's length", () => {
    expect(projectedMonthUsd(10, "2026-08-22")).toBe(310);
    expect(projectedMonthUsd(10, "2026-02-10")).toBe(280);
  });

  it.each([
    // Non-colliding: the rounded stop already clears the warn line.
    [
      12.4,
      {
        day: { warnUsd: 20, stopUsd: 50 },
        month: { warnUsd: 500, stopUsd: 1000 },
      },
    ],
    // Both pairs would round onto one rung; each stop steps up to the next.
    [
      11,
      {
        day: { warnUsd: 20, stopUsd: 50 },
        month: { warnUsd: 500, stopUsd: 1000 },
      },
    ],
    // Only the monthly pair collides here.
    [
      5,
      {
        day: { warnUsd: 5, stopUsd: 10 },
        month: { warnUsd: 200, stopUsd: 500 },
      },
    ],
    // A low average collides on both periods.
    [
      2.4,
      {
        day: { warnUsd: 5, stopUsd: 10 },
        month: { warnUsd: 100, stopUsd: 200 },
      },
    ],
  ] as const)(
    "suggests round lines with a warn below the stop for %d/day",
    (avgDailyUsd, expected) => {
      const suggested = suggestedSpendLimits(avgDailyUsd, "2026-08-22");
      expect(suggested).toEqual(expected);
      // The warn line must stay strictly below the stop so its notice can fire.
      expect(suggested?.day.warnUsd).toBeLessThan(suggested?.day.stopUsd ?? 0);
      expect(suggested?.month.warnUsd).toBeLessThan(
        suggested?.month.stopUsd ?? 0,
      );
    },
  );

  it("returns null without history to derive lines from", () => {
    expect(suggestedSpendLimits(0, "2026-08-22")).toBeNull();
  });

  it.each([
    ["20", 20],
    ["$20", 20],
    ["8,950", 8950],
    ["12.345", 12.35],
    ["", null],
    ["0", null],
    ["-5", null],
    ["abc", null],
  ] as const)("parseSpendAmount(%j) -> %s", (raw, expected) => {
    expect(parseSpendAmount(raw)).toBe(expected);
  });

  it.each([
    // A day's average anchors the daily track.
    [100, 12.4, 10],
    // A month's pace, rounded, then halved until enough ticks fit.
    [2000, 384, 250],
    // No reference figure: fall back to a readable division of the scale.
    [100, null, 10],
    [10, null, 1],
    // A reference so large it would leave one tick gets halved until enough
    // fit.
    [100, 90, 12.5],
    [0, 12, 0],
  ] as const)(
    "spendTickIncrement(%s, %s) -> %s",
    (scale, reference, expected) => {
      expect(spendTickIncrement(scale, reference)).toBe(expected);
    },
  );

  it("always leaves between 6 and 12 ticks on the track", () => {
    for (const scale of [10, 50, 100, 500, 2000, 20000]) {
      for (const reference of [null, 0.5, 12.4, 384, 9000]) {
        const increment = spendTickIncrement(scale, reference);
        const ticks = scale / increment;
        expect(ticks).toBeGreaterThanOrEqual(6);
        expect(ticks).toBeLessThanOrEqual(12);
      }
    }
  });

  it("maskStops keeps both warn values and nulls both stop values", () => {
    const input: SpendLimits = {
      day: { warnUsd: 20, stopUsd: 50 },
      month: { warnUsd: 200, stopUsd: 500 },
    };
    expect(maskStops(input)).toEqual({
      day: { warnUsd: 20, stopUsd: null },
      month: { warnUsd: 200, stopUsd: null },
    });
  });
});
