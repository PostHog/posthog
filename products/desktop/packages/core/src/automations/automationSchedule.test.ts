import { describe, expect, it } from "vitest";
import {
  type AutomationScheduleDraft,
  buildCronExpression,
  createDefaultScheduleDraft,
  deriveAutomationName,
  formatAutomationScheduleSummary,
  formatScheduleSummary,
  parseCronExpression,
  sanitizeHour,
  sanitizeMinute,
  WEEKDAY_OPTIONS,
} from "./automationSchedule";

describe("automationSchedule", () => {
  it("creates the default daily schedule draft", () => {
    expect(createDefaultScheduleDraft()).toEqual({
      mode: "daily",
      hour: "09",
      minute: "00",
      weekday: "1",
      rawCron: "0 9 * * *",
    });
  });

  it("provides cron weekday values in display order", () => {
    expect(WEEKDAY_OPTIONS).toEqual([
      { value: "1", label: "Mon" },
      { value: "2", label: "Tue" },
      { value: "3", label: "Wed" },
      { value: "4", label: "Thu" },
      { value: "5", label: "Fri" },
      { value: "6", label: "Sat" },
      { value: "0", label: "Sun" },
    ]);
  });

  it.each([
    ["", ""],
    ["a", ""],
    ["7", "07"],
    ["09", "09"],
    ["2x3", "23"],
    ["24", "23"],
    ["999", "23"],
  ])("sanitizes hour input %j to %j", (input, expected) => {
    expect(sanitizeHour(input)).toBe(expected);
  });

  it.each([
    ["", ""],
    ["a", ""],
    ["7", "07"],
    ["09", "09"],
    ["5x9", "59"],
    ["60", "59"],
    ["999", "59"],
  ])("sanitizes minute input %j to %j", (input, expected) => {
    expect(sanitizeMinute(input)).toBe(expected);
  });

  it.each<{
    name: string;
    changes: Partial<AutomationScheduleDraft>;
    expected: string;
  }>([
    {
      name: "hourly",
      changes: { mode: "hourly", minute: "15" },
      expected: "15 * * * *",
    },
    {
      name: "daily",
      changes: { mode: "daily", hour: "09", minute: "15" },
      expected: "15 9 * * *",
    },
    {
      name: "weekdays",
      changes: { mode: "weekdays", hour: "10", minute: "00" },
      expected: "0 10 * * 1-5",
    },
    {
      name: "weekly",
      changes: {
        mode: "weekly",
        hour: "11",
        minute: "30",
        weekday: "4",
      },
      expected: "30 11 * * 4",
    },
    {
      name: "weekly with a missing weekday",
      changes: { mode: "weekly", weekday: "" },
      expected: "0 9 * * 1",
    },
    {
      name: "preset with missing time values",
      changes: { mode: "daily", hour: "", minute: "" },
      expected: "0 9 * * *",
    },
    {
      name: "custom",
      changes: { mode: "custom", rawCron: "  */15 * * * *  " },
      expected: "*/15 * * * *",
    },
  ])("builds the $name cron expression", ({ changes, expected }) => {
    expect(
      buildCronExpression({ ...createDefaultScheduleDraft(), ...changes }),
    ).toBe(expected);
  });

  it.each([
    [
      "15 * * * *",
      {
        mode: "hourly",
        hour: "09",
        minute: "15",
        weekday: "*",
        rawCron: "15 * * * *",
      },
    ],
    [
      "0 9 * * *",
      {
        mode: "daily",
        hour: "09",
        minute: "00",
        weekday: "*",
        rawCron: "0 9 * * *",
      },
    ],
    [
      "0 9 * * 1-5",
      {
        mode: "weekdays",
        hour: "09",
        minute: "00",
        weekday: "1",
        rawCron: "0 9 * * 1-5",
      },
    ],
    [
      "30 14 * * 2",
      {
        mode: "weekly",
        hour: "14",
        minute: "30",
        weekday: "2",
        rawCron: "30 14 * * 2",
      },
    ],
  ] as const)("parses %s into a schedule draft", (cron, expected) => {
    expect(parseCronExpression(cron)).toEqual(expected);
  });

  it.each(["*/15 * * * *", "0 9 1 * *", "0 9 * 1 *", "0 9 * * 1,3"])(
    "keeps unsupported cron expression %s in custom mode",
    (cron) => {
      expect(parseCronExpression(cron)).toMatchObject({
        mode: "custom",
        rawCron: cron,
      });
    },
  );

  it("normalizes surrounding and repeated cron whitespace", () => {
    expect(parseCronExpression("  5   8  * * *  ")).toEqual({
      mode: "daily",
      hour: "08",
      minute: "05",
      weekday: "*",
      rawCron: "5   8  * * *",
    });
  });

  it("uses default draft fields for a cron expression with the wrong arity", () => {
    expect(parseCronExpression("0 9 * *")).toEqual({
      mode: "custom",
      hour: "09",
      minute: "00",
      weekday: "1",
      rawCron: "0 9 * *",
    });
  });

  it("derives a compact name from the first non-empty prompt line", () => {
    expect(
      deriveAutomationName(
        "\n  Review   every open PostHog PR for stale comments \nIgnore this line",
      ),
    ).toBe("Review every open PostHog PR for stale comments");
  });

  it("returns an empty name for a blank prompt", () => {
    expect(deriveAutomationName(" \n\t\n ")).toBe("");
  });

  it("limits derived names to 80 characters", () => {
    expect(deriveAutomationName("a".repeat(100))).toBe("a".repeat(80));
  });

  it.each([
    ["15 * * * *", "Europe/London", "Every hour at :15 · Europe/London"],
    ["0 9 * * *", null, "Daily at 09:00"],
    ["0 9 * * 1-5", "UTC", "Weekdays at 09:00 · UTC"],
    ["30 14 * * 2", undefined, "Tue at 14:30"],
    ["30 14 * * 7", "UTC", "Weekly at 14:30 · UTC"],
    ["*/15 * * * *", "UTC", "Custom schedule · UTC"],
  ])("formats %s with timezone %j", (cronExpression, timezone, expected) => {
    expect(formatScheduleSummary(cronExpression, timezone)).toBe(expected);
  });

  it("formats a schedule from an automation-shaped input", () => {
    expect(
      formatAutomationScheduleSummary({
        cron_expression: "0 18 * * 0",
        timezone: "America/New_York",
      }),
    ).toBe("Sun at 18:00 · America/New_York");
  });
});
