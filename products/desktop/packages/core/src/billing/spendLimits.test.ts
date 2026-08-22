import { describe, expect, it } from "vitest";
import {
  EMPTY_SPEND_LIMITS,
  evaluateSpendLimits,
  hasAnySpendLimit,
  pruneSpendNoticesSeen,
  type SpendLimits,
  spendLimitNoticeKey,
  spendTotalsFromDays,
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
      name: "alert supersedes warn for the same period",
      limits: { dailyWarnUsd: 20, dailyAlertUsd: 50 },
      totals: { todayUsd: 60, monthUsd: 60 },
      expected: [{ period: "day", level: "alert", limitUsd: 50 }],
    },
    {
      name: "daily and monthly cross independently",
      limits: { dailyWarnUsd: 20, monthlyAlertUsd: 200 },
      totals: { todayUsd: 25, monthUsd: 250 },
      expected: [
        { period: "day", level: "warn", limitUsd: 20 },
        { period: "month", level: "alert", limitUsd: 200 },
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
      level: "alert",
      limitUsd: 50,
      spentUsd: 61,
      anchor: TODAY,
    });
    expect(key).toBe("day:alert:2026-08-22:50");
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
        "day:alert:2026-08-22:50": "2026-08-22",
        "month:alert:2026-08:200": "2026-08",
      },
      TODAY,
    );
    expect(Object.keys(pruned).sort()).toEqual([
      "day:alert:2026-08-22:50",
      "month:alert:2026-08:200",
    ]);
  });

  it("reports whether any line is set", () => {
    expect(hasAnySpendLimit(EMPTY_SPEND_LIMITS)).toBe(false);
    expect(hasAnySpendLimit(limits({ monthlyWarnUsd: 100 }))).toBe(true);
  });
});
