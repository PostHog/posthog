import { describe, expect, it } from "vitest";
import { compileCronSchedule, parseCronSchedule } from "./loopCron";

describe("parseCronSchedule", () => {
  it.each([
    {
      cron: "0 * * * *",
      expected: { frequency: "hourly", time: "09:00", weekday: "1" },
    },
    {
      cron: "30 9 * * *",
      expected: { frequency: "daily", time: "09:30", weekday: "1" },
    },
    {
      cron: "0 17 * * 1-5",
      expected: { frequency: "weekdays", time: "17:00", weekday: "1" },
    },
    {
      cron: "15 8 * * 3",
      expected: { frequency: "weekly", time: "08:15", weekday: "3" },
    },
    {
      cron: "  5  7  *  *  * ",
      expected: { frequency: "daily", time: "07:05", weekday: "1" },
    },
  ])("parses picker-shaped cron $cron", ({ cron, expected }) => {
    expect(parseCronSchedule(cron)).toEqual(expected);
  });

  it.each([
    { name: "empty", cron: "" },
    { name: "null", cron: null },
    { name: "undefined", cron: undefined },
    { name: "step minutes", cron: "*/15 * * * *" },
    { name: "day of month", cron: "0 9 1 * *" },
    { name: "specific month", cron: "0 9 * 6 *" },
    { name: "weekday list", cron: "0 9 * * 1,3,5" },
    { name: "hourly on a weekday", cron: "0 * * * 1" },
    { name: "non-zero hourly minute", cron: "30 * * * *" },
    { name: "wildcard minute", cron: "* 9 * * *" },
    { name: "minute out of range", cron: "60 9 * * *" },
    { name: "hour out of range", cron: "0 24 * * *" },
    { name: "six fields", cron: "0 0 9 * * *" },
    { name: "named weekday", cron: "0 9 * * MON" },
  ])("returns null for $name so it renders as custom", ({ cron }) => {
    expect(parseCronSchedule(cron)).toBeNull();
  });
});

describe("compileCronSchedule", () => {
  it.each([
    { frequency: "hourly", time: "09:30", weekday: "2", cron: "0 * * * *" },
    { frequency: "daily", time: "09:30", weekday: "2", cron: "30 9 * * *" },
    {
      frequency: "weekdays",
      time: "17:00",
      weekday: "2",
      cron: "0 17 * * 1-5",
    },
    { frequency: "weekly", time: "08:15", weekday: "3", cron: "15 8 * * 3" },
    { frequency: "daily", time: "", weekday: "1", cron: "0 0 * * *" },
  ] as const)(
    "compiles $frequency $time to $cron",
    ({ frequency, time, weekday, cron }) => {
      expect(compileCronSchedule(frequency, time, weekday)).toBe(cron);
    },
  );

  it.each([
    { frequency: "daily", time: "09:30", weekday: "1" },
    { frequency: "weekdays", time: "06:05", weekday: "1" },
    { frequency: "weekly", time: "23:45", weekday: "6" },
  ] as const)(
    "round-trips $frequency $time through parse",
    ({ frequency, time, weekday }) => {
      expect(
        parseCronSchedule(compileCronSchedule(frequency, time, weekday)),
      ).toEqual({ frequency, time, weekday });
    },
  );
});
