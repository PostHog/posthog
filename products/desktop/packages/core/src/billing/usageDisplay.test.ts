import { describe, expect, it } from "vitest";
import type { UsageOutput } from "../usage/schemas";
import {
  codeOrgSpendLimitUsd,
  codeUsageMeter,
  formatResetTime,
  formatUsageBreakdown,
  formatUsdAmount,
  isCodeUsageFreeTier,
  isUsageExceeded,
} from "./usageDisplay";

function makeUsage(
  overrides: Partial<{
    sustained: boolean;
    burst: boolean;
    isRateLimited: boolean;
  }> = {},
): UsageOutput {
  return {
    product: "posthog_code",
    user_id: 1,
    sustained: {
      used_percent: 50,
      reset_at: "2026-05-01T13:00:00.000Z",
      exceeded: overrides.sustained ?? false,
    },
    burst: {
      used_percent: 30,
      reset_at: "2026-05-01T12:10:00.000Z",
      exceeded: overrides.burst ?? false,
    },
    is_rate_limited: overrides.isRateLimited ?? false,
    is_pro: false,
  };
}

describe("isUsageExceeded", () => {
  it("returns false when nothing is exceeded", () => {
    expect(isUsageExceeded(makeUsage())).toBe(false);
  });

  it("returns true when sustained is exceeded", () => {
    expect(isUsageExceeded(makeUsage({ sustained: true }))).toBe(true);
  });

  it("returns true when burst is exceeded", () => {
    expect(isUsageExceeded(makeUsage({ burst: true }))).toBe(true);
  });

  it("returns true when rate limited", () => {
    expect(isUsageExceeded(makeUsage({ isRateLimited: true }))).toBe(true);
  });

  it("returns true when all flags are set", () => {
    expect(
      isUsageExceeded(
        makeUsage({ sustained: true, burst: true, isRateLimited: true }),
      ),
    ).toBe(true);
  });
});

describe("isCodeUsageFreeTier", () => {
  it.each([
    [false, true],
    [true, false],
    // Absent means unknown, never free.
    [undefined, false],
  ] as const)("code_usage_subscribed=%s -> %s", (subscribed, expected) => {
    expect(isCodeUsageFreeTier({ code_usage_subscribed: subscribed })).toBe(
      expected,
    );
  });

  it("treats missing usage as not confirmed free", () => {
    expect(isCodeUsageFreeTier(null)).toBe(false);
    expect(isCodeUsageFreeTier(undefined)).toBe(false);
  });
});

describe("codeUsageMeter", () => {
  it("prefers billing's org dollars when both numbers are present", () => {
    const meter = codeUsageMeter({
      ...makeUsage(),
      code_usage_subscribed: true,
      ai_credits: { exhausted: false, used_usd: 12.4, limit_usd: 50 },
      billing_period_end: "2026-06-01T00:00:00.000Z",
    });
    expect(meter).toEqual({
      kind: "dollars",
      usedUsd: 12.4,
      limitUsd: 50,
      percent: 25,
      exceeded: false,
      resetAt: "2026-06-01T00:00:00.000Z",
      breakdown: { includedUsd: 20, spendLimitUsd: 30 },
    });
  });

  it("splits a default-settings subscribed limit into $20 included + $50 spend limit", () => {
    const meter = codeUsageMeter({
      ...makeUsage(),
      code_usage_subscribed: true,
      ai_credits: { exhausted: false, used_usd: 5, limit_usd: 70 },
    });
    expect(meter).toMatchObject({
      kind: "dollars",
      limitUsd: 70,
      breakdown: { includedUsd: 20, spendLimitUsd: 50 },
    });
  });

  it("keeps a free org's dollars meter breakdown-free — its limit is just the allowance", () => {
    const meter = codeUsageMeter({
      ...makeUsage(),
      code_usage_subscribed: false,
      ai_credits: { exhausted: false, used_usd: 5, limit_usd: 20 },
    });
    expect(meter).toMatchObject({ kind: "dollars", breakdown: null });
  });

  it("marks the dollars meter exceeded from the org bucket and falls back to the sustained reset", () => {
    const meter = codeUsageMeter({
      ...makeUsage(),
      code_usage_subscribed: false,
      ai_credits: { exhausted: true, used_usd: 20, limit_usd: 20 },
    });
    expect(meter).toMatchObject({
      kind: "dollars",
      percent: 100,
      exceeded: true,
      resetAt: "2026-05-01T13:00:00.000Z",
    });
  });

  it.each([
    ["missing numbers", { exhausted: false }],
    ["null numbers", { exhausted: false, used_usd: null, limit_usd: null }],
    ["a zero limit", { exhausted: false, used_usd: 0, limit_usd: 0 }],
  ])("falls back to the free-tier valve bucket with %s", (_name, aiCredits) => {
    const usage: UsageOutput = {
      ...makeUsage(),
      code_usage_subscribed: false,
      ai_credits: aiCredits,
    };
    expect(codeUsageMeter(usage)).toEqual({
      kind: "bucket",
      bucket: usage.sustained,
    });
  });

  it("hides the meter for a subscribed or unknown org without dollars", () => {
    expect(
      codeUsageMeter({ ...makeUsage(), code_usage_subscribed: true }),
    ).toEqual({ kind: "hidden" });
    expect(codeUsageMeter(makeUsage())).toEqual({ kind: "hidden" });
    expect(codeUsageMeter(null)).toEqual({ kind: "hidden" });
  });
});

describe("codeOrgSpendLimitUsd", () => {
  const subscribedWithLimit = (limitUsd: number | null) => ({
    code_usage_subscribed: true,
    ai_credits: { exhausted: false, used_usd: 0, limit_usd: limitUsd },
  });

  it.each([
    ["default settings", 70, 50],
    ["custom limit", 120.5, 100.5],
    ["a $0 spend limit is a real answer", 20, 0],
  ])("recovers the configured limit with %s", (_name, limitUsd, expected) => {
    expect(codeOrgSpendLimitUsd(subscribedWithLimit(limitUsd))).toBe(expected);
  });

  it("returns null when the merged limit is below the allowance", () => {
    expect(codeOrgSpendLimitUsd(subscribedWithLimit(15))).toBeNull();
  });

  it("returns null without a limit number", () => {
    expect(codeOrgSpendLimitUsd(subscribedWithLimit(null))).toBeNull();
    expect(
      codeOrgSpendLimitUsd({
        code_usage_subscribed: true,
        ai_credits: undefined,
      }),
    ).toBeNull();
  });

  it("returns null for free, unknown, or missing orgs", () => {
    expect(
      codeOrgSpendLimitUsd({
        code_usage_subscribed: false,
        ai_credits: { exhausted: false, used_usd: 0, limit_usd: 20 },
      }),
    ).toBeNull();
    expect(
      codeOrgSpendLimitUsd({
        code_usage_subscribed: undefined,
        ai_credits: { exhausted: false, used_usd: 0, limit_usd: 70 },
      }),
    ).toBeNull();
    expect(codeOrgSpendLimitUsd(null)).toBeNull();
  });
});

describe("formatUsageBreakdown", () => {
  it("phrases the merged limit as included + spend limit", () => {
    expect(formatUsageBreakdown({ includedUsd: 20, spendLimitUsd: 50 })).toBe(
      "$20 included + $50 org spend limit",
    );
  });
});

describe("formatUsdAmount", () => {
  it.each([
    [50, "$50"],
    [12.4, "$12.40"],
    [0.5, "$0.50"],
    [0, "$0"],
  ])("formats %s as %s", (amount, expected) => {
    expect(formatUsdAmount(amount)).toBe(expected);
  });
});

describe("formatResetTime", () => {
  const NOW = Date.parse("2026-05-01T12:00:00.000Z");
  const isoAt = (msFromNow: number) => new Date(NOW + msFromNow).toISOString();

  it.each([
    {
      name: "returns minutes-only under 1h",
      resetAt: isoAt(30 * 60 * 1000),
      expected: "Resets in 30m" as string | RegExp,
    },
    {
      name: "returns hours + minutes under 24h",
      resetAt: isoAt((4 * 3600 + 30 * 60) * 1000),
      expected: "Resets in 4h 30m",
    },
    {
      name: "returns hours only when minutes round to 0",
      resetAt: isoAt(4 * 3600 * 1000),
      expected: "Resets in 4h",
    },
    {
      name: "rolls the hour instead of showing 60 minutes",
      resetAt: isoAt((23 * 3600 + 59 * 60 + 40) * 1000),
      expected: "Resets in 24h",
    },
    {
      name: "returns localized date when over 24h away",
      resetAt: isoAt(30 * 86400 * 1000),
      expected: /^Resets [A-Za-z]+ \d+ at /,
    },
    {
      name: "treats an already-past reset_at as shortly",
      resetAt: isoAt(-60_000),
      expected: "Resets shortly",
    },
    {
      name: "treats an unparseable reset_at as shortly",
      resetAt: "not-a-date",
      expected: "Resets shortly",
    },
  ])("$name", ({ resetAt, expected }) => {
    const result = formatResetTime(resetAt, { now: NOW });
    if (expected instanceof RegExp) {
      expect(result).toMatch(expected);
    } else {
      expect(result).toBe(expected);
    }
  });

  it("swaps the leading phrase when a custom label is given", () => {
    const opts = { now: NOW, label: "Billing period ends" };
    expect(formatResetTime(isoAt(30 * 60 * 1000), opts)).toBe(
      "Billing period ends in 30m",
    );
    expect(formatResetTime(isoAt(4 * 3600 * 1000), opts)).toBe(
      "Billing period ends in 4h",
    );
    expect(formatResetTime(isoAt(-60_000), opts)).toBe(
      "Billing period ends shortly",
    );
    expect(formatResetTime(isoAt(30 * 86400 * 1000), opts)).toMatch(
      /^Billing period ends [A-Za-z]+ \d+ at /,
    );
  });
});
