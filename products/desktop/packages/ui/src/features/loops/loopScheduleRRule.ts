import type { WorkflowSchemas } from "@posthog/api-client/workflows";
import { nextRecurringRun } from "@posthog/ui/primitives/nextRecurringRun";
import { compileCronSchedule, parseCronSchedule } from "./loopCron";

/** Maps the loop form's schedule-trigger config (a cron string or a one-time `run_at`, the
 * same shape the Loops API uses) onto a `HogFlowSchedule` write, the sub-resource HogFlows use
 * for timing instead of a cron field on the trigger itself.
 *
 * Only the shapes the form's own frequency picker writes round-trip; anything else (a cron the
 * picker doesn't recognize) returns null and the caller should treat the loop as not
 * decompilable — see `isDecompilableLoopSchedule`. */
export function loopScheduleTriggerConfigToRRuleWrite(
  config: { cron_expression?: string; timezone?: string; run_at?: string },
  now = new Date(),
): WorkflowSchemas.HogFlowScheduleWrite | null {
  if (config.run_at) {
    return {
      rrule: "FREQ=DAILY;COUNT=1",
      starts_at: config.run_at,
      timezone: "UTC",
    };
  }

  const parsed = parseCronSchedule(config.cron_expression);
  if (!parsed) return null;
  const timezone = config.timezone ?? "UTC";
  const startsAt = nextRecurringRun(parsed, timezone, now);
  if (!startsAt) return null;

  return {
    rrule: recurringFrequencyToRRule(parsed.frequency, parsed.weekday),
    starts_at: startsAt.toISOString(),
    timezone,
  };
}

const WEEKDAY_TO_RRULE_DAY: Record<string, string> = {
  "0": "SU",
  "1": "MO",
  "2": "TU",
  "3": "WE",
  "4": "TH",
  "5": "FR",
  "6": "SA",
};

function recurringFrequencyToRRule(
  frequency: "hourly" | "daily" | "weekdays" | "weekly",
  weekday: string,
): string {
  switch (frequency) {
    case "hourly":
      return "FREQ=HOURLY";
    case "daily":
      return "FREQ=DAILY";
    case "weekdays":
      return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
    case "weekly":
      return `FREQ=WEEKLY;BYDAY=${WEEKDAY_TO_RRULE_DAY[weekday] ?? "MO"}`;
  }
}

const RRULE_TO_RECURRING: Record<
  string,
  { frequency: "hourly" | "daily" | "weekdays" | "weekly"; weekday: string }
> = {
  "FREQ=HOURLY": { frequency: "hourly", weekday: "1" },
  "FREQ=DAILY": { frequency: "daily", weekday: "1" },
  "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR": { frequency: "weekdays", weekday: "1" },
};

/** Reverses `loopScheduleTriggerConfigToRRuleWrite` for exactly the RRULE shapes it writes.
 * Returns null for an RRULE this feature didn't author, e.g. one edited through the main-app
 * workflow schedule UI. */
export function rruleScheduleToLoopTriggerConfig(
  schedule: Pick<
    WorkflowSchemas.HogFlowSchedule,
    "rrule" | "starts_at" | "timezone"
  >,
): { cron_expression: string; timezone: string } | { run_at: string } | null {
  if (isOnceOffSchedule(schedule.rrule)) {
    return { run_at: schedule.starts_at };
  }
  const recurring = RRULE_TO_RECURRING[schedule.rrule];
  if (recurring) {
    const time = isoTimeInZone(schedule.starts_at, schedule.timezone);
    return {
      cron_expression: compileCronSchedule(
        recurring.frequency,
        time,
        recurring.weekday,
      ),
      timezone: schedule.timezone,
    };
  }
  const weeklyMatch = schedule.rrule.match(
    /^FREQ=WEEKLY;BYDAY=(SU|MO|TU|WE|TH|FR|SA)$/,
  );
  if (weeklyMatch) {
    const weekday = Object.entries(WEEKDAY_TO_RRULE_DAY).find(
      ([, day]) => day === weeklyMatch[1],
    )?.[0];
    if (weekday) {
      const time = isoTimeInZone(schedule.starts_at, schedule.timezone);
      return {
        cron_expression: compileCronSchedule("weekly", time, weekday),
        timezone: schedule.timezone,
      };
    }
  }
  return null;
}

export function isOnceOffSchedule(rrule: string): boolean {
  return rrule === "FREQ=DAILY;COUNT=1";
}

function isoTimeInZone(iso: string, timezone: string): string {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hourCycle: "h23",
    hour: "2-digit",
    minute: "2-digit",
  });
  const parts = Object.fromEntries(
    formatter
      .formatToParts(new Date(iso))
      .map(({ type, value }) => [type, value]),
  );
  return `${parts.hour}:${parts.minute}`;
}
