import type { SignalTeamConfig } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  dailyReportLimitFieldValue,
  describeDailyReportLimit,
  parseDailyReportLimit,
} from "./dailyReportLimit";

function config(overrides: Partial<SignalTeamConfig> = {}): SignalTeamConfig {
  return {
    id: "config-1",
    default_autostart_priority: "P2",
    max_reports_per_day: null,
    reports_generated_today: 0,
    daily_report_limit_reached: false,
    created_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:00:00Z",
    ...overrides,
  } as SignalTeamConfig;
}

describe("parseDailyReportLimit", () => {
  it.each([
    ["saves a positive integer", "5", { ok: true, value: 5 }],
    ["trims surrounding whitespace", "  12  ", { ok: true, value: 12 }],
    ["clears on empty input", "", { ok: true, value: null }],
    ["clears on whitespace-only input", "   ", { ok: true, value: null }],
  ])("%s", (_name, input, expected) => {
    expect(parseDailyReportLimit(input)).toEqual(expected);
  });

  it.each([["0"], ["-3"], ["2.5"], ["ten"], ["9999999999999"]])(
    "rejects %s",
    (input) => {
      const result = parseDailyReportLimit(input);
      expect(result.ok).toBe(false);
    },
  );
});

describe("describeDailyReportLimit", () => {
  it("reports no limit when the cap is unset", () => {
    const status = describeDailyReportLimit(
      config({ max_reports_per_day: null }),
    );
    expect(status.limit).toBeNull();
    expect(status.reached).toBe(false);
    expect(status.reachedText).toBeNull();
    expect(status.usageText).toContain("No daily limit");
  });

  it("shows the server count against the cap", () => {
    const status = describeDailyReportLimit(
      config({ max_reports_per_day: 10, reports_generated_today: 3 }),
    );
    expect(status.today).toBe(3);
    expect(status.usageText).toBe("3 of 10 reports used today.");
  });

  it("explains the pause when the limit is reached", () => {
    const status = describeDailyReportLimit(
      config({
        max_reports_per_day: 2,
        reports_generated_today: 2,
        daily_report_limit_reached: true,
      }),
    );
    expect(status.reached).toBe(true);
    expect(status.reachedText).toContain("midnight in the project's timezone");
  });

  it("treats a missing config as no limit", () => {
    const status = describeDailyReportLimit(null);
    expect(status.limit).toBeNull();
    expect(status.usageText).toContain("No daily limit");
  });
});

describe("dailyReportLimitFieldValue", () => {
  it.each([
    ["empty when unlimited", null, ""],
    ["the cap as text when set", 7, "7"],
  ])("%s", (_name, limit, expected) => {
    expect(
      dailyReportLimitFieldValue(config({ max_reports_per_day: limit })),
    ).toBe(expected);
  });
});
