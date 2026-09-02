import type { HogFlowScheduleWrite } from "@posthog/api-client/hogFlowLoops";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { parseCronSchedule } from "./loopCron";

const WEEKDAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"] as const;
const WORKWEEK = "MO,TU,WE,TH,FR";

/** Anything beyond these keys means a person edited the rule outside the loop
 * form, and the four presets can no longer describe it. */
const KNOWN_RRULE_KEYS = new Set([
  "FREQ",
  "INTERVAL",
  "COUNT",
  "BYDAY",
  "BYHOUR",
  "BYMINUTE",
  "BYSECOND",
]);

function timeParts(time: string): { hour: number; minute: number } {
  const [hour, minute] = time.split(":").map(Number);
  return { hour, minute };
}

function timedRule(freq: string, time: string, byDay?: string): string {
  const { hour, minute } = timeParts(time);
  const parts = [`FREQ=${freq}`];
  if (byDay) parts.push(`BYDAY=${byDay}`);
  parts.push(`BYHOUR=${hour}`, `BYMINUTE=${minute}`, "BYSECOND=0");
  return parts.join(";");
}

/**
 * Turns the loop form's schedule into a workflow schedule row. Returns null for
 * a cron the frequency picker cannot express, so a caller never sends a rule
 * that silently drops part of the cadence.
 *
 * Presets anchor `starts_at` at `now`: the rule carries the clock time itself
 * (BYHOUR/BYMINUTE), so the anchor only bounds the first occurrence. A one-off
 * anchors at `run_at` with COUNT=1, so the single occurrence is the anchor.
 */
export function scheduleConfigToHogFlowSchedule(
  config: LoopSchemas.LoopScheduleTriggerConfig,
  now: Date = new Date(),
): HogFlowScheduleWrite | null {
  const timezone = config.timezone ?? "UTC";
  if (config.run_at) {
    return { rrule: "FREQ=DAILY;COUNT=1", starts_at: config.run_at, timezone };
  }
  const schedule = parseCronSchedule(config.cron_expression);
  if (!schedule) return null;
  const starts_at = now.toISOString();
  switch (schedule.frequency) {
    case "hourly":
      return {
        rrule: "FREQ=HOURLY;BYMINUTE=0;BYSECOND=0",
        starts_at,
        timezone,
      };
    case "daily":
      return { rrule: timedRule("DAILY", schedule.time), starts_at, timezone };
    case "weekdays":
      return {
        rrule: timedRule("WEEKLY", schedule.time, WORKWEEK),
        starts_at,
        timezone,
      };
    case "weekly":
      return {
        rrule: timedRule(
          "WEEKLY",
          schedule.time,
          WEEKDAY_CODES[Number(schedule.weekday)],
        ),
        starts_at,
        timezone,
      };
  }
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

function cronTime(parts: Map<string, string>): string | null {
  const hour = Number(parts.get("BYHOUR"));
  const minute = Number(parts.get("BYMINUTE") ?? "0");
  if (!parts.has("BYHOUR") || !Number.isInteger(hour) || hour > 23) {
    return null;
  }
  if (!Number.isInteger(minute) || minute > 59) return null;
  return `${minute} ${hour}`;
}

/**
 * Reads a workflow schedule row back into the loop form's schedule config.
 * Returns null when the rule is not one the form wrote, which marks the loop as
 * edited outside the form rather than guessing at a nearby preset.
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
  if ((parts.get("BYSECOND") ?? "0") !== "0") return null;
  const timezone = schedule.timezone ?? "UTC";
  const freq = parts.get("FREQ");

  if (parts.has("COUNT")) {
    if (parts.get("COUNT") !== "1" || freq !== "DAILY") return null;
    if (parts.has("BYHOUR") || parts.has("BYDAY")) return null;
    return { run_at: schedule.starts_at, timezone };
  }

  if (freq === "HOURLY") {
    if ((parts.get("BYMINUTE") ?? "0") !== "0" || parts.has("BYHOUR")) {
      return null;
    }
    return { cron_expression: "0 * * * *", timezone };
  }

  const time = cronTime(parts);
  if (!time) return null;

  if (freq === "DAILY") {
    if (parts.has("BYDAY")) return null;
    return { cron_expression: `${time} * * *`, timezone };
  }

  if (freq === "WEEKLY") {
    const byDay = parts.get("BYDAY");
    if (byDay === WORKWEEK) {
      return { cron_expression: `${time} * * 1-5`, timezone };
    }
    const weekday = WEEKDAY_CODES.indexOf(
      byDay as (typeof WEEKDAY_CODES)[number],
    );
    if (weekday === -1) return null;
    return { cron_expression: `${time} * * ${weekday}`, timezone };
  }

  return null;
}

/**
 * Whether an existing schedule row already expresses the desired cadence. A
 * preset ignores `starts_at`, because rewriting the anchor makes the scheduler
 * recompute `next_run_at` and can skip an occurrence that was about to fire.
 */
export function hogFlowScheduleMatches(
  existing: { rrule: string; starts_at: string; timezone?: string | null },
  desired: HogFlowScheduleWrite,
): boolean {
  if (existing.rrule !== desired.rrule) return false;
  if ((existing.timezone ?? "UTC") !== desired.timezone) return false;
  if (!desired.rrule.includes("COUNT=1")) return true;
  return (
    new Date(existing.starts_at).getTime() ===
    new Date(desired.starts_at).getTime()
  );
}
