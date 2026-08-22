import { describe, expect, it } from "vitest";
import {
  activeSpendStop,
  EMPTY_SPEND_LIMITS,
  evaluateSpendLimits,
  hasAnySpendLimit,
  niceRound,
  projectedMonthUsd,
  pruneSpendNoticesSeen,
  type SpendLimits,
  spendLimitNoticeKey,
  spendTotalsFromDays,
  suggestedSpendLimits,
} from "./spendLimits";

const TODAY = "2026-08-22";

function limits(partial: Partial<SpendLimits>): SpendLimits {
  return { ...EMPTY_SPEND_LIMITS, ...partial };
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
    limits: Partial<SpendLimits>;
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
      limits: { dailyWarnUsd: 20 },
      totals: { todayUsd: 19.99, monthUsd: 19.99 },
      expected: [],
    },
    {
      name: "spend exactly on the line crosses",
      limits: { dailyWarnUsd: 20 },
      totals: { todayUsd: 20, monthUsd: 20 },
      expected: [{ period: "day", level: "warn", limitUsd: 20 }],
    },
    {
      name: "stop supersedes warn for the same period",
      limits: { dailyWarnUsd: 20, dailyStopUsd: 50 },
      totals: { todayUsd: 60, monthUsd: 60 },
      expected: [{ period: "day", level: "stop", limitUsd: 50 }],
    },
    {
      name: "daily and monthly cross independently",
      limits: { dailyWarnUsd: 20, monthlyStopUsd: 200 },
      totals: { todayUsd: 25, monthUsd: 250 },
      expected: [
        { period: "day", level: "warn", limitUsd: 20 },
        { period: "month", level: "stop", limitUsd: 200 },
      ],
    },
    {
      name: "a zero line is treated as off",
      limits: { dailyWarnUsd: 0 },
      totals: { todayUsd: 5, monthUsd: 5 },
      expected: [],
    },
  ])("$name", ({ limits: partial, totals, expected }) => {
    const crossings = evaluateSpendLimits(limits(partial), totals, TODAY);
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
      limits({ dailyWarnUsd: 20 }),
      { todayUsd: 30, monthUsd: 30 },
      TODAY,
    )[0];
    const at25 = evaluateSpendLimits(
      limits({ dailyWarnUsd: 25 }),
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

  it("reports whether any line is set", () => {
    expect(hasAnySpendLimit(EMPTY_SPEND_LIMITS)).toBe(false);
    expect(hasAnySpendLimit(limits({ monthlyWarnUsd: 100 }))).toBe(true);
  });

  it("holds work on the daily stop line before the monthly one", () => {
    const both = limits({ dailyStopUsd: 50, monthlyStopUsd: 400 });
    expect(
      activeSpendStop(both, { todayUsd: 60, monthUsd: 500 }),
    ).toMatchObject({ period: "day", limitUsd: 50 });
    expect(
      activeSpendStop(both, { todayUsd: 10, monthUsd: 500 }),
    ).toMatchObject({ period: "month", limitUsd: 400 });
    expect(activeSpendStop(both, { todayUsd: 10, monthUsd: 100 })).toBeNull();
    expect(
      activeSpendStop(EMPTY_SPEND_LIMITS, { todayUsd: 999, monthUsd: 999 }),
    ).toBeNull();
  });

  it("projects the month from the daily average and the month's length", () => {
    expect(projectedMonthUsd(10, "2026-08-22")).toBe(310);
    expect(projectedMonthUsd(10, "2026-02-10")).toBe(280);
  });

  it.each([
    [18.6, 20],
    [37.2, 50],
    [2.6, 2],
    [387.5, 500],
  ] as const)("niceRound(%s) -> %s", (value, expected) => {
    expect(niceRound(value)).toBe(expected);
  });

  it("suggests round lines from the user's history", () => {
    expect(suggestedSpendLimits(12.4, "2026-08-22")).toEqual({
      dailyWarnUsd: 20,
      dailyStopUsd: 50,
      monthlyWarnUsd: 500,
      monthlyStopUsd: 1000,
    });
    expect(suggestedSpendLimits(0, "2026-08-22")).toBeNull();
  });
});
