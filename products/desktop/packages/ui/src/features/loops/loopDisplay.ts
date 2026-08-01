import type { LoopSchemas } from "@posthog/api-client/loops";
import { formatClockTime } from "@posthog/shared";
import { nextRecurringRun } from "@posthog/ui/primitives/nextRecurringRun";
import {
  formatTimezoneAbbreviation,
  systemTimezone,
} from "@posthog/ui/primitives/timezone";
import { parseCronSchedule } from "./loopCron";

const WEEKDAY_NAMES: Record<string, string> = {
  "0": "Sunday",
  "1": "Monday",
  "2": "Tuesday",
  "3": "Wednesday",
  "4": "Thursday",
  "5": "Friday",
  "6": "Saturday",
};

function describeSchedule(
  config: LoopSchemas.LoopScheduleTriggerConfig,
): string {
  const cron = config.cron_expression;
  const parsed = parseCronSchedule(cron);
  const timezone = config.timezone ?? "UTC";
  const timezoneLabel = formatTimezoneAbbreviation(timezone);
  if (!parsed) return `${cron ?? "?"} (${timezoneLabel})`;
  if (parsed.frequency === "hourly") return `Every hour (${timezoneLabel})`;

  const time = formatClockTime(parsed.time);
  if (parsed.frequency === "daily")
    return `Daily at ${time} (${timezoneLabel})`;
  if (parsed.frequency === "weekdays")
    return `Weekdays at ${time} (${timezoneLabel})`;
  return `${WEEKDAY_NAMES[parsed.weekday]}s at ${time} (${timezoneLabel})`;
}

export function nextScheduleRun(
  config: LoopSchemas.LoopScheduleTriggerConfig,
  now = new Date(),
): Date | null {
  if (config.run_at) {
    const runAt = new Date(config.run_at);
    return runAt > now ? runAt : null;
  }

  const schedule = parseCronSchedule(config.cron_expression);
  if (!schedule) return null;
  return nextRecurringRun(schedule, config.timezone ?? "UTC", now);
}

function describeNextRun(
  config: LoopSchemas.LoopScheduleTriggerConfig,
): string {
  const nextRun = nextScheduleRun(config);
  if (!nextRun) return "";
  const timezone =
    config.timezone ?? (config.run_at ? systemTimezone() : "UTC");
  const formatted = new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(nextRun);
  return ` · Next run ${formatted}`;
}

type LoopStatusFields = Pick<
  LoopSchemas.Loop,
  "enabled" | "disabled_reason" | "last_run_status"
>;

export function loopStatusColor(
  loop: LoopStatusFields,
): "gray" | "green" | "red" {
  if (!loop.enabled) return loop.disabled_reason ? "red" : "gray";
  if (loop.last_run_status === "failed") return "red";
  return "green";
}

export function loopStatusLabel(loop: LoopStatusFields): string {
  if (!loop.enabled) {
    if (loop.disabled_reason === "usage_limited") return "Paused: usage limit";
    if (loop.disabled_reason) return "Auto-paused";
    return "Paused";
  }
  if (loop.last_run_status === "failed") return "Failing";
  return "Active";
}

const PAUSED_DESCRIPTIONS: Record<string, string> = {
  usage_limited:
    "Paused automatically: your organization reached its usage limit. Upgrade or wait for the limit to reset, then re-enable the loop.",
  repeated_failures:
    "Paused automatically after too many failed runs in a row. Check the last run's error, then re-enable the loop.",
  owner_deactivated: "Paused because its owner's account was deactivated.",
  owner_removed_from_org: "Paused because its owner left the organization.",
  github_integration_disconnected:
    "Paused because its GitHub connection was removed.",
};

/** Sentence explaining a backend-driven pause, or null for an enabled loop or a
 * normal owner pause. */
export function loopPausedDescription(loop: LoopStatusFields): string | null {
  if (loop.enabled || !loop.disabled_reason) return null;
  return PAUSED_DESCRIPTIONS[loop.disabled_reason] ?? "Paused automatically.";
}

const FIRE_BLOCKED_MESSAGES: Record<string, string> = {
  deduped: "An identical run was already started for this trigger.",
  overlap_skipped: "The previous run is still in progress.",
  rate_capped: "This loop reached its daily run cap.",
  team_rate_capped: "Your team reached its daily loop run cap.",
  disabled: "This loop or its trigger is disabled.",
  gate_blocked: "Your organization reached its usage limit.",
  owner_inactive: "The loop owner's account can no longer start runs.",
  owner_changed:
    "The loop's owner changed while the run was starting. Try again.",
};

export function loopFireBlockedMessage(
  reason: LoopSchemas.LoopFireReasonEnum,
): string {
  return FIRE_BLOCKED_MESSAGES[reason] ?? `Run not started: ${reason}`;
}

interface TriggerLike {
  type: LoopSchemas.LoopTriggerTypeEnum;
  config: LoopSchemas.LoopTriggerConfig;
}

export function summarizeNotificationDestinations(
  notifications: LoopSchemas.LoopNotifications,
): string[] {
  const destinations: string[] = [];

  if (notifications.push.enabled) destinations.push("Push");
  if (notifications.email.enabled) destinations.push("Email");
  if (notifications.slack.enabled) {
    const channelName = notifications.slack.params.channel_name;
    destinations.push(
      typeof channelName === "string" && channelName.length > 0
        ? `Slack · #${channelName.replace(/^#/, "")}`
        : "Slack",
    );
  }

  return destinations;
}

/** Readable label for the form's review list. */
export function summarizeTrigger(trigger: TriggerLike): string {
  if (trigger.type === "schedule") {
    const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
    if (config.run_at)
      return `Once · ${new Date(config.run_at).toLocaleString()}`;
    return `${describeSchedule(config)}${describeNextRun(config)}`;
  }
  if (trigger.type === "github") {
    const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
    return `GitHub (${config.repository || "a repo"})`;
  }
  return "API";
}

/** Full description for the detail view's configuration summary. */
export function describeTrigger(trigger: TriggerLike): string {
  if (trigger.type === "schedule") {
    const config = trigger.config as LoopSchemas.LoopScheduleTriggerConfig;
    if (config.run_at)
      return `One-time · ${new Date(config.run_at).toLocaleString()}${describeNextRun(config)}`;
    return `Schedule · ${describeSchedule(config)}${describeNextRun(config)}`;
  }
  if (trigger.type === "github") {
    const config = trigger.config as LoopSchemas.LoopGithubTriggerConfig;
    return `GitHub · ${config.repository || "?"} · ${config.events.join(", ") || "no events"}`;
  }
  return "API · authenticated POST";
}
