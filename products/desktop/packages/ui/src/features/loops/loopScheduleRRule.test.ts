import { describe, expect, it } from "vitest";
import {
  hogFlowScheduleMatches,
  hogFlowScheduleToScheduleConfig,
  scheduleConfigToHogFlowSchedule,
} from "./loopScheduleRRule";

const NOW = new Date("2026-09-02T10:37:12.000Z");

function must<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("expected a value");
  return value;
}

describe("loopScheduleRRule", () => {
  it.each([
    ["hourly", "0 * * * *", "FREQ=HOURLY;BYMINUTE=0;BYSECOND=0"],
    ["daily", "0 9 * * *", "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0"],
    [
      "weekdays",
      "30 8 * * 1-5",
      "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=8;BYMINUTE=30;BYSECOND=0",
    ],
    [
      "weekly",
      "15 17 * * 3",
      "FREQ=WEEKLY;BYDAY=WE;BYHOUR=17;BYMINUTE=15;BYSECOND=0",
    ],
    [
      "sunday",
      "0 6 * * 0",
      "FREQ=WEEKLY;BYDAY=SU;BYHOUR=6;BYMINUTE=0;BYSECOND=0",
    ],
  ])("round-trips the %s preset", (_label, cron, rrule) => {
    const config = { cron_expression: cron, timezone: "Europe/Lisbon" };
    const schedule = scheduleConfigToHogFlowSchedule(config, NOW);
    expect(schedule).toEqual({
      rrule,
      starts_at: NOW.toISOString(),
      timezone: "Europe/Lisbon",
    });
    expect(hogFlowScheduleToScheduleConfig(must(schedule))).toEqual(config);
  });

  it("round-trips a one-off run as a single-occurrence rule anchored at run_at", () => {
    const config = { run_at: "2026-09-03T14:00:00.000Z", timezone: "UTC" };
    const schedule = scheduleConfigToHogFlowSchedule(config, NOW);
    expect(schedule).toEqual({
      rrule: "FREQ=DAILY;COUNT=1",
      starts_at: "2026-09-03T14:00:00.000Z",
      timezone: "UTC",
    });
    expect(hogFlowScheduleToScheduleConfig(must(schedule))).toEqual(config);
  });

  it("defaults a missing timezone to UTC in both directions", () => {
    expect(
      scheduleConfigToHogFlowSchedule({ cron_expression: "0 9 * * *" }, NOW)
        ?.timezone,
    ).toBe("UTC");
    expect(
      hogFlowScheduleToScheduleConfig({
        rrule: "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
        starts_at: NOW.toISOString(),
      }),
    ).toEqual({ cron_expression: "0 9 * * *", timezone: "UTC" });
  });

  it.each(["*/15 * * * *", "0 9 1 * *", "0 9 * * 1,3", "", undefined])(
    "refuses a cron the picker cannot express: %s",
    (cron) => {
      expect(
        scheduleConfigToHogFlowSchedule({ cron_expression: cron }, NOW),
      ).toBeNull();
    },
  );

  it.each([
    [
      "a two-day interval",
      "FREQ=DAILY;INTERVAL=2;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    ],
    [
      "a monthly rule",
      "FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
    ],
    ["an end date", "FREQ=DAILY;UNTIL=20261231T000000Z;BYHOUR=9;BYMINUTE=0"],
    ["two weekdays", "FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=0;BYSECOND=0"],
    ["a daily rule with no clock time", "FREQ=DAILY"],
    ["a count above one", "FREQ=DAILY;COUNT=3"],
    ["an hourly rule off the hour", "FREQ=HOURLY;BYMINUTE=30"],
    ["a malformed segment", "FREQ=DAILY;BYHOUR"],
  ])("reads a rule the form did not write as foreign: %s", (_label, rrule) => {
    expect(
      hogFlowScheduleToScheduleConfig({
        rrule,
        starts_at: NOW.toISOString(),
        timezone: "UTC",
      }),
    ).toBeNull();
  });

  it("treats a preset as unchanged when only starts_at differs", () => {
    const desired = must(
      scheduleConfigToHogFlowSchedule(
        { cron_expression: "0 9 * * *", timezone: "UTC" },
        NOW,
      ),
    );
    const existing = { ...desired, starts_at: "2026-01-01T00:00:00Z" };
    expect(hogFlowScheduleMatches(existing, desired)).toBe(true);
    expect(
      hogFlowScheduleMatches(
        { ...existing, timezone: "Europe/Lisbon" },
        desired,
      ),
    ).toBe(false);
    expect(
      hogFlowScheduleMatches({ ...existing, timezone: null }, desired),
    ).toBe(true);
  });

  it("treats a one-off as changed when run_at moves", () => {
    const desired = must(
      scheduleConfigToHogFlowSchedule(
        { run_at: "2026-09-03T14:00:00.000Z" },
        NOW,
      ),
    );
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-09-03T14:00:00+00:00" },
        desired,
      ),
    ).toBe(true);
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-09-04T14:00:00.000Z" },
        desired,
      ),
    ).toBe(false);
  });
});
