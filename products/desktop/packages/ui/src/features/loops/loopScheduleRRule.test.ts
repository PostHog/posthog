import { describe, expect, it } from "vitest";
import {
  isOnceOffSchedule,
  loopScheduleTriggerConfigToRRuleWrite,
  rruleScheduleToLoopTriggerConfig,
} from "./loopScheduleRRule";

// A fixed Monday so "next occurrence" math is deterministic across runs.
const NOW = new Date("2026-01-05T00:00:00.000Z");

describe("loopScheduleTriggerConfigToRRuleWrite", () => {
  it("maps a one-time run_at to a COUNT=1 marker rrule", () => {
    const result = loopScheduleTriggerConfigToRRuleWrite({
      run_at: "2026-02-01T09:00:00.000Z",
    });
    expect(result).toEqual({
      rrule: "FREQ=DAILY;COUNT=1",
      starts_at: "2026-02-01T09:00:00.000Z",
      timezone: "UTC",
    });
  });

  it("maps hourly to FREQ=HOURLY", () => {
    const result = loopScheduleTriggerConfigToRRuleWrite(
      { cron_expression: "0 * * * *", timezone: "UTC" },
      NOW,
    );
    expect(result?.rrule).toBe("FREQ=HOURLY");
    expect(result?.timezone).toBe("UTC");
  });

  it("maps daily to FREQ=DAILY", () => {
    const result = loopScheduleTriggerConfigToRRuleWrite(
      { cron_expression: "30 9 * * *", timezone: "UTC" },
      NOW,
    );
    expect(result?.rrule).toBe("FREQ=DAILY");
  });

  it("maps weekdays to FREQ=WEEKLY with the five weekday codes", () => {
    const result = loopScheduleTriggerConfigToRRuleWrite(
      { cron_expression: "0 17 * * 1-5", timezone: "UTC" },
      NOW,
    );
    expect(result?.rrule).toBe("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR");
  });

  it("maps a specific weekday to FREQ=WEEKLY with that day's code", () => {
    const result = loopScheduleTriggerConfigToRRuleWrite(
      { cron_expression: "15 8 * * 3", timezone: "UTC" },
      NOW,
    );
    expect(result?.rrule).toBe("FREQ=WEEKLY;BYDAY=WE");
  });

  it("returns null for a cron the picker itself wouldn't have written", () => {
    // Step values and day-of-month lists aren't representable by the picker.
    expect(
      loopScheduleTriggerConfigToRRuleWrite(
        { cron_expression: "*/15 * * * *", timezone: "UTC" },
        NOW,
      ),
    ).toBeNull();
  });

  it("returns null when neither run_at nor a recognized cron is set", () => {
    expect(loopScheduleTriggerConfigToRRuleWrite({}, NOW)).toBeNull();
  });
});

describe("rruleScheduleToLoopTriggerConfig / loopScheduleTriggerConfigToRRuleWrite round-trip", () => {
  it.each([
    { cron_expression: "0 * * * *", timezone: "UTC" },
    { cron_expression: "30 9 * * *", timezone: "Europe/London" },
    { cron_expression: "0 17 * * 1-5", timezone: "UTC" },
    { cron_expression: "15 8 * * 3", timezone: "America/New_York" },
  ])("round-trips $cron_expression in $timezone", (config) => {
    const written = loopScheduleTriggerConfigToRRuleWrite(config, NOW);
    expect(written).not.toBeNull();
    // biome-ignore lint/style/noNonNullAssertion: asserted above
    const { rrule, starts_at, timezone } = written!;
    const decompiled = rruleScheduleToLoopTriggerConfig({
      rrule,
      starts_at,
      timezone: timezone ?? "UTC",
    });
    expect(decompiled).toEqual({
      cron_expression: config.cron_expression,
      timezone: config.timezone,
    });
  });

  it("returns null for an rrule this feature didn't author", () => {
    expect(
      rruleScheduleToLoopTriggerConfig({
        rrule: "FREQ=MONTHLY;BYMONTHDAY=1",
        starts_at: NOW.toISOString(),
        timezone: "UTC",
      }),
    ).toBeNull();
  });

  it("maps the once-off marker rrule back to a run_at, not a recurring cron", () => {
    expect(
      rruleScheduleToLoopTriggerConfig({
        rrule: "FREQ=DAILY;COUNT=1",
        starts_at: NOW.toISOString(),
        timezone: "UTC",
      }),
    ).toEqual({ run_at: NOW.toISOString() });
  });
});

describe("isOnceOffSchedule", () => {
  it("recognizes the once-off marker rrule", () => {
    expect(isOnceOffSchedule("FREQ=DAILY;COUNT=1")).toBe(true);
    expect(isOnceOffSchedule("FREQ=DAILY")).toBe(false);
  });
});
