import type {
  RecurringSchedule,
  RecurringScheduleFrequency,
} from "@posthog/ui/primitives/nextRecurringRun";

export const DEFAULT_SCHEDULE_TIME = "09:00";

export type RecurringFrequency = RecurringScheduleFrequency;

export type ParsedRecurringSchedule = RecurringSchedule;

/** Reads the shapes the frequency picker writes. Anything else (step values,
 * day-of-month, day lists, ...) returns null and must be treated as a custom
 * schedule, never silently recompiled into a picker shape. */
export function parseCronSchedule(
  cron: string | null | undefined,
): ParsedRecurringSchedule | null {
  if (!cron) return null;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  if (dayOfMonth !== "*" || month !== "*") return null;
  if (!/^\d{1,2}$/.test(minute)) return null;
  const minuteNumber = Number(minute);
  if (minuteNumber > 59) return null;
  if (hour === "*") {
    return minute === "0" && dayOfWeek === "*"
      ? { frequency: "hourly", time: DEFAULT_SCHEDULE_TIME, weekday: "1" }
      : null;
  }
  if (!/^\d{1,2}$/.test(hour)) return null;
  if (Number(hour) > 23) return null;
  const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  if (dayOfWeek === "*") return { frequency: "daily", time, weekday: "1" };
  if (dayOfWeek === "1-5") return { frequency: "weekdays", time, weekday: "1" };
  if (/^[0-6]$/.test(dayOfWeek)) {
    return { frequency: "weekly", time, weekday: dayOfWeek };
  }
  return null;
}

export function compileCronSchedule(
  frequency: RecurringFrequency,
  time: string,
  weekday: string,
): string {
  const [hourPart, minutePart] = time.split(":");
  const hour = Number(hourPart) || 0;
  const minute = Number(minutePart) || 0;
  switch (frequency) {
    case "hourly":
      return "0 * * * *";
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekdays":
      return `${minute} ${hour} * * 1-5`;
    case "weekly":
      return `${minute} ${hour} * * ${weekday}`;
  }
}
