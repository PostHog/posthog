import type { TaskAutomation } from "../types";

export type AutomationScheduleMode =
  | "hourly"
  | "daily"
  | "weekdays"
  | "weekly"
  | "custom";

export interface AutomationScheduleDraft {
  mode: AutomationScheduleMode;
  hour: string;
  minute: string;
  weekday: string;
  rawCron: string;
}

export const WEEKDAY_OPTIONS = [
  { value: "1", label: "Mon" },
  { value: "2", label: "Tue" },
  { value: "3", label: "Wed" },
  { value: "4", label: "Thu" },
  { value: "5", label: "Fri" },
  { value: "6", label: "Sat" },
  { value: "0", label: "Sun" },
] as const;

export function createDefaultScheduleDraft(): AutomationScheduleDraft {
  return {
    mode: "daily",
    hour: "09",
    minute: "00",
    weekday: "1",
    rawCron: "0 9 * * *",
  };
}

function padTimePart(value: string): string {
  return value.padStart(2, "0");
}

export function sanitizeHour(value: string): string {
  const digitsOnly = value.replace(/\D/g, "").slice(0, 2);
  if (!digitsOnly) {
    return "";
  }

  return String(Math.min(23, Number(digitsOnly))).padStart(2, "0");
}

export function sanitizeMinute(value: string): string {
  const digitsOnly = value.replace(/\D/g, "").slice(0, 2);
  if (!digitsOnly) {
    return "";
  }

  return String(Math.min(59, Number(digitsOnly))).padStart(2, "0");
}

export function buildCronExpression(draft: AutomationScheduleDraft): string {
  if (draft.mode === "custom") {
    return draft.rawCron.trim();
  }

  const minute = draft.minute ? String(Number(draft.minute)) : "0";
  const hour = draft.hour ? String(Number(draft.hour)) : "9";

  switch (draft.mode) {
    case "hourly":
      return `${minute} * * * *`;
    case "weekdays":
      return `${minute} ${hour} * * 1-5`;
    case "weekly":
      return `${minute} ${hour} * * ${draft.weekday || "1"}`;
    default:
      return `${minute} ${hour} * * *`;
  }
}

export function parseCronExpression(
  cronExpression: string,
): AutomationScheduleDraft {
  const normalized = cronExpression.trim();
  const parts = normalized.split(/\s+/);

  if (parts.length !== 5) {
    return {
      ...createDefaultScheduleDraft(),
      mode: "custom",
      rawCron: normalized,
    };
  }

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  const isNumericMinute = /^\d{1,2}$/.test(minute);
  const isNumericHour = /^\d{1,2}$/.test(hour);
  const draftBase = {
    hour: padTimePart(hour),
    minute: padTimePart(minute),
    weekday: dayOfWeek,
    rawCron: normalized,
  };

  if (
    isNumericMinute &&
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return {
      ...draftBase,
      mode: "hourly",
      hour: "09",
    };
  }

  if (
    isNumericMinute &&
    isNumericHour &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    return {
      ...draftBase,
      mode: "daily",
    };
  }

  if (
    isNumericMinute &&
    isNumericHour &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "1-5"
  ) {
    return {
      ...draftBase,
      mode: "weekdays",
      weekday: "1",
    };
  }

  if (
    isNumericMinute &&
    isNumericHour &&
    dayOfMonth === "*" &&
    month === "*" &&
    /^\d$/.test(dayOfWeek)
  ) {
    return {
      ...draftBase,
      mode: "weekly",
    };
  }

  return {
    ...draftBase,
    mode: "custom",
  };
}

export function deriveAutomationName(prompt: string): string {
  const normalized = prompt
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);

  if (!normalized) {
    return "";
  }

  return normalized.replace(/\s+/g, " ").slice(0, 80);
}

function formatTime(hour: string, minute: string): string {
  return `${padTimePart(hour)}:${padTimePart(minute)}`;
}

export function formatScheduleSummary(
  cronExpression: string,
  timezone: string | null | undefined,
): string {
  const draft = parseCronExpression(cronExpression);
  const suffix = timezone ? ` · ${timezone}` : "";

  switch (draft.mode) {
    case "hourly":
      return `Every hour at :${padTimePart(draft.minute)}${suffix}`;
    case "weekdays":
      return `Weekdays at ${formatTime(draft.hour, draft.minute)}${suffix}`;
    case "weekly": {
      const label =
        WEEKDAY_OPTIONS.find((option) => option.value === draft.weekday)
          ?.label ?? "Weekly";
      return `${label} at ${formatTime(draft.hour, draft.minute)}${suffix}`;
    }
    case "custom":
      return `Custom schedule${suffix}`;
    default:
      return `Daily at ${formatTime(draft.hour, draft.minute)}${suffix}`;
  }
}

export function formatAutomationScheduleSummary(
  automation: Pick<TaskAutomation, "cron_expression" | "timezone">,
): string {
  return formatScheduleSummary(
    automation.cron_expression,
    automation.timezone ?? null,
  );
}
