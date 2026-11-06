import { describe, expect, it } from "vitest";
import {
  hogFlowScheduleMatches,
  hogFlowScheduleToScheduleConfig,
  scheduleConfigToHogFlowSchedule,
} from "./loopScheduleRRule";

// A Wednesday, 10:37 UTC (11:37 in Lisbon, which is on summer time).
const NOW = new Date("2026-09-02T10:37:12.000Z");

function must<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("expected a value");
  return value;
}

/** Clock time and weekday of an instant in a timezone, as the editor shows it. */
function inZone(instant: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hourCycle: "h23",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(instant));
}

describe("loopScheduleRRule", () => {
  it.each([
    ["hourly", "0 * * * *", "FREQ=HOURLY;INTERVAL=1", "Wed 12:00"],
    ["daily", "0 9 * * *", "FREQ=DAILY;INTERVAL=1", "Thu 09:00"],
    [
      "weekdays",
      "30 8 * * 1-5",
      "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR",
      "Thu 08:30",
    ],
    ["weekly", "15 17 * * 3", "FREQ=WEEKLY;INTERVAL=1;BYDAY=WE", "Wed 17:15"],
    ["sunday", "0 6 * * 0", "FREQ=WEEKLY;INTERVAL=1;BYDAY=SU", "Sun 06:00"],
  ])(
    "round-trips the %s preset with the clock time in starts_at",
    (_label, cron, rrule, startsAtInLisbon) => {
      const config = { cron_expression: cron, timezone: "Europe/Lisbon" };
      const schedule = must(scheduleConfigToHogFlowSchedule(config, NOW));
      expect(schedule.rrule).toBe(rrule);
      expect(schedule.timezone).toBe("Europe/Lisbon");
      expect(inZone(schedule.starts_at, "Europe/Lisbon")).toBe(
        startsAtInLisbon,
      );
      expect(new Date(schedule.starts_at).getTime()).toBeGreaterThan(
        NOW.getTime(),
      );
      expect(hogFlowScheduleToScheduleConfig(schedule)).toEqual(config);
    },
  );

  it("round-trips a one-off run as the editor's one-time rule anchored at run_at", () => {
    const config = { run_at: "2026-09-03T14:00:00.000Z", timezone: "UTC" };
    const schedule = scheduleConfigToHogFlowSchedule(config, NOW);
    expect(schedule).toEqual({
      rrule: "FREQ=DAILY;COUNT=1",
      starts_at: "2026-09-03T14:00:00.000Z",
      timezone: "UTC",
    });
    expect(hogFlowScheduleToScheduleConfig(must(schedule))).toEqual(config);
  });

  it("reads the clock time in the schedule's timezone, not UTC", () => {
    expect(
      hogFlowScheduleToScheduleConfig({
        rrule: "FREQ=DAILY;INTERVAL=1",
        starts_at: "2026-09-02T08:00:00Z",
        timezone: "Europe/Lisbon",
      }),
    ).toEqual({ cron_expression: "0 9 * * *", timezone: "Europe/Lisbon" });
  });

  it("reads a weekly rule with no BYDAY as the weekday of starts_at, like the editor", () => {
    expect(
      hogFlowScheduleToScheduleConfig({
        rrule: "FREQ=WEEKLY;INTERVAL=1",
        starts_at: "2027-01-01T00:00:00Z",
        timezone: "UTC",
      }),
    ).toEqual({ cron_expression: "0 0 * * 5", timezone: "UTC" });
  });

  it("defaults a missing timezone to UTC in both directions", () => {
    expect(
      scheduleConfigToHogFlowSchedule({ cron_expression: "0 9 * * *" }, NOW)
        ?.timezone,
    ).toBe("UTC");
    expect(
      hogFlowScheduleToScheduleConfig({
        rrule: "FREQ=DAILY;INTERVAL=1",
        starts_at: "2026-09-03T09:00:00Z",
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
    ["a two-day interval", "FREQ=DAILY;INTERVAL=2", "2026-09-03T09:00:00Z"],
    ["a monthly rule", "FREQ=MONTHLY;BYMONTHDAY=1", "2026-09-03T09:00:00Z"],
    [
      "an end date",
      "FREQ=DAILY;UNTIL=20261231T000000Z",
      "2026-09-03T09:00:00Z",
    ],
    [
      "two weekdays",
      "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE",
      "2026-09-03T09:00:00Z",
    ],
    [
      "a clock time inside the rule",
      "FREQ=DAILY;BYHOUR=9;BYMINUTE=0",
      "2026-09-03T09:00:00Z",
    ],
    ["a count above one", "FREQ=DAILY;COUNT=3", "2026-09-03T09:00:00Z"],
    [
      "an hourly rule off the hour",
      "FREQ=HOURLY;INTERVAL=1",
      "2026-09-03T09:30:00Z",
    ],
    ["a malformed segment", "FREQ=DAILY;BYDAY", "2026-09-03T09:00:00Z"],
    ["an unreadable anchor", "FREQ=DAILY;INTERVAL=1", "not a date"],
  ])(
    "reads a rule the form did not write as foreign: %s",
    (_label, rrule, startsAt) => {
      expect(
        hogFlowScheduleToScheduleConfig({
          rrule,
          starts_at: startsAt,
          timezone: "UTC",
        }),
      ).toBeNull();
    },
  );

  it("treats a preset as unchanged when starts_at moves but keeps its clock time", () => {
    const desired = must(
      scheduleConfigToHogFlowSchedule(
        { cron_expression: "0 9 * * *", timezone: "Europe/Lisbon" },
        NOW,
      ),
    );
    // 08:00 UTC in January is 08:00 Lisbon (winter time), a different clock time.
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-01-05T09:00:00Z" },
        desired,
      ),
    ).toBe(true);
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-01-05T08:00:00Z" },
        desired,
      ),
    ).toBe(false);
    expect(
      hogFlowScheduleMatches({ ...desired, timezone: "UTC" }, desired),
    ).toBe(false);
  });

  it("treats an hourly preset as unchanged when only the anchor hour moves", () => {
    const desired = must(
      scheduleConfigToHogFlowSchedule(
        { cron_expression: "0 * * * *", timezone: "Europe/Lisbon" },
        NOW,
      ),
    );
    expect(inZone(desired.starts_at, "Europe/Lisbon")).toBe("Wed 12:00");
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-09-02T08:00:00Z" },
        desired,
      ),
    ).toBe(true);
    expect(
      hogFlowScheduleMatches(
        { ...desired, starts_at: "2026-09-02T08:30:00Z" },
        desired,
      ),
    ).toBe(false);
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
