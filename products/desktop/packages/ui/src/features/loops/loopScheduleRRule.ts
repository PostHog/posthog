import type { HogFlowScheduleWrite } from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { nextRecurringRun } from "@posthog/ui/primitives/nextRecurringRun";
import { parseCronSchedule } from "./loopCron";

/**
 * Loop schedule <-> workflow schedule row, in the shape the workflow editor
 * writes: the RRULE carries frequency, interval and weekdays only, and the
 * time of day lives in `starts_at`. The scheduler expands the rule from
 * `starts_at` in the schedule's timezone, and the editor reads the clock time
 * back from it, so a rule that carries its own BYHOUR would show one time in
 * the editor and fire at another.
 */

const WEEKDAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"] as const;
const WORKWEEK = "MO,TU,WE,TH,FR";
/** Same string the workflow editor writes for a one-time schedule. */
const ONE_TIME_RRULE = "FREQ=DAILY;COUNT=1";

/** Anything beyond these keys means a person edited the rule outside the loop
 * form, and the four presets can no longer describe it. */
const KNOWN_RRULE_KEYS = new Set([
  "FREQ",
  "INTERVAL",
  "COUNT",
  "BYDAY",
  "WKST",
]);

interface WallClock {
  /** 0 to 23. */
  hour: number;
  minute: number;
  /** "0" (Sunday) to "6" (Saturday), matching cron and the loop picker. */
  weekday: string;
}

const WEEKDAY_BY_SHORT_NAME: Record<string, string> = {
  Sun: "0",
  Mon: "1",
  Tue: "2",
  Wed: "3",
  Thu: "4",
  Fri: "5",
  Sat: "6",
};

/** The clock time and weekday of an instant in a timezone, or null when the
 * instant or the timezone cannot be read. */
function wallClock(instant: string, timezone: string): WallClock | null {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return null;
  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      hourCycle: "h23",
      hour: "2-digit",
      minute: "2-digit",
      weekday: "short",
    }).formatToParts(date);
  } catch {
    return null;
  }
  const read = (type: string) =>
    parts.find((part) => part.type === type)?.value;
  const hour = read("hour");
  const minute = read("minute");
  const weekday = WEEKDAY_BY_SHORT_NAME[read("weekday") ?? ""];
  if (!hour || !minute || !weekday) return null;
  // Some engines render midnight as "24" under h23.
  return {
    hour: hour === "24" ? 0 : Number(hour),
    minute: Number(minute),
    weekday,
  };
}

function presetRRule(frequency: string, weekday: string): string {
  switch (frequency) {
    case "hourly":
      return "FREQ=HOURLY;INTERVAL=1";
    case "daily":
      return "FREQ=DAILY;INTERVAL=1";
    case "weekdays":
      return `FREQ=WEEKLY;INTERVAL=1;BYDAY=${WORKWEEK}`;
    default:
      return `FREQ=WEEKLY;INTERVAL=1;BYDAY=${WEEKDAY_CODES[Number(weekday)]}`;
  }
}

/**
 * Turns the loop form's schedule into a workflow schedule row. Returns null for
 * a cron the frequency picker cannot express, so a caller never sends a rule
 * that silently drops part of the cadence.
 *
 * `starts_at` is the next occurrence at the chosen time in the schedule's
 * timezone, so the row reads the same in the workflow editor as in the loop.
 */
export function scheduleConfigToHogFlowSchedule(
  config: LoopSchemas.LoopScheduleTriggerConfig,
  now: Date = new Date(),
): HogFlowScheduleWrite | null {
  const timezone = config.timezone ?? "UTC";
  if (config.run_at) {
    return { rrule: ONE_TIME_RRULE, starts_at: config.run_at, timezone };
  }
  const schedule = parseCronSchedule(config.cron_expression);
  if (!schedule) return null;
  const startsAt = nextRecurringRun(schedule, timezone, now);
  if (!startsAt) return null;
  return {
    rrule: presetRRule(schedule.frequency, schedule.weekday),
    starts_at: startsAt.toISOString(),
    timezone,
  };
}

function parseRRule(rrule: string): Map<string, string> | null {
  const parts = new Map<string, string>();
  for (const segment of rrule.split(";")) {
    if (!segment.trim()) continue;
    const [key, value, ...rest] = segment.split("=");
    if (!key || value === undefined || rest.length > 0) return null;
    parts.set(key.trim().toUpperCase(), value.trim().toUpperCase());
  }
  return parts;
}

/**
 * Reads a workflow schedule row back into the loop form's schedule config.
 * Returns null when the rule is not one the form (or the workflow editor's
 * matching controls) would write, which marks the loop as edited outside the
 * form rather than guessing at a nearby preset.
 */
export function hogFlowScheduleToScheduleConfig(schedule: {
  rrule: string;
  starts_at: string;
  timezone?: string | null;
}): LoopSchemas.LoopScheduleTriggerConfig | null {
  const parts = parseRRule(schedule.rrule);
  if (!parts) return null;
  for (const key of parts.keys()) {
    if (!KNOWN_RRULE_KEYS.has(key)) return null;
  }
  if ((parts.get("INTERVAL") ?? "1") !== "1") return null;
  const timezone = schedule.timezone ?? "UTC";
  const freq = parts.get("FREQ");
  const byDay = parts.get("BYDAY");

  if (parts.has("COUNT")) {
    if (parts.get("COUNT") !== "1" || freq !== "DAILY" || byDay) return null;
    return { run_at: schedule.starts_at, timezone };
  }

  const clock = wallClock(schedule.starts_at, timezone);
  if (!clock) return null;
  const { hour, minute } = clock;
  const cronTime = `${minute} ${hour}`;

  if (freq === "HOURLY") {
    // The picker's hourly preset is on the hour; an anchor at :30 would fire
    // at :30 and cannot be shown as "hourly".
    if (byDay || minute !== 0) return null;
    return { cron_expression: "0 * * * *", timezone };
  }
  if (freq === "DAILY") {
    if (byDay) return null;
    return { cron_expression: `${cronTime} * * *`, timezone };
  }
  if (freq === "WEEKLY") {
    if (byDay === WORKWEEK) {
      return { cron_expression: `${cronTime} * * 1-5`, timezone };
    }
    // No BYDAY means the weekday of starts_at, which is how the editor
    // stores a weekly schedule before a day pill is picked.
    if (!byDay) {
      return { cron_expression: `${cronTime} * * ${clock.weekday}`, timezone };
    }
    const weekday = WEEKDAY_CODES.indexOf(
      byDay as (typeof WEEKDAY_CODES)[number],
    );
    if (weekday === -1) return null;
    return { cron_expression: `${cronTime} * * ${weekday}`, timezone };
  }
  return null;
}

/**
 * Whether an existing schedule row already expresses the desired cadence. A
 * preset compares the clock time `starts_at` encodes rather than the instant,
 * because rewriting the anchor makes the scheduler recompute `next_run_at`
 * and can skip an occurrence that was about to fire. An hourly rule fires
 * every hour from its anchor, so only the anchor's minute carries cadence.
 */
export function hogFlowScheduleMatches(
  existing: { rrule: string; starts_at: string; timezone?: string | null },
  desired: HogFlowScheduleWrite,
): boolean {
  if (existing.rrule !== desired.rrule) return false;
  const timezone = existing.timezone ?? "UTC";
  if (timezone !== desired.timezone) return false;
  if (desired.rrule === ONE_TIME_RRULE) {
    return (
      new Date(existing.starts_at).getTime() ===
      new Date(desired.starts_at).getTime()
    );
  }
  const before = wallClock(existing.starts_at, timezone);
  const after = wallClock(desired.starts_at, timezone);
  if (!before || !after) return false;
  if (before.minute !== after.minute) return false;
  const hourly = parseRRule(desired.rrule)?.get("FREQ") === "HOURLY";
  return hourly || before.hour === after.hour;
}
