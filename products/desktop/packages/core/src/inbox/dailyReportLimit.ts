import type { SignalTeamConfig } from "@posthog/shared/types";

/** Ceiling matches the backend int4 column max, so an over-range value is rejected before the request. */
const MAX_DAILY_REPORT_LIMIT = 2147483647;

export type DailyReportLimitParseResult =
  | { ok: true; value: number | null }
  | { ok: false; error: string };

/**
 * Turn the text field into a value for `max_reports_per_day`. Empty text clears
 * the cap (`null`). Anything else must be a whole number from 1 to the column
 * ceiling; otherwise the parse fails with copy the caller can show.
 */
export function parseDailyReportLimit(
  input: string,
): DailyReportLimitParseResult {
  const trimmed = input.trim();
  if (trimmed === "") {
    return { ok: true, value: null };
  }

  if (!/^\d+$/.test(trimmed)) {
    return {
      ok: false,
      error:
        "Enter a whole number of 1 or more, or leave it empty for no limit.",
    };
  }

  const value = Number(trimmed);
  if (value < 1 || value > MAX_DAILY_REPORT_LIMIT) {
    return {
      ok: false,
      error:
        "Enter a whole number of 1 or more, or leave it empty for no limit.",
    };
  }

  return { ok: true, value };
}

export interface DailyReportLimitStatus {
  /** The saved cap, or `null` when reports are unlimited. */
  limit: number | null;
  /** Reports that first reached the inbox today. `0` when there is no cap. */
  today: number;
  /** True when the cap is reached and new reports are paused until local midnight. */
  reached: boolean;
  /** One-line summary of today's usage, shown under the field. */
  usageText: string;
  /** Message shown when the cap is reached; `null` otherwise. */
  reachedText: string | null;
}

/**
 * Read a team config into the display state for the daily-limit control. The
 * count and reached flag come from the server, so this is a pure projection.
 */
export function describeDailyReportLimit(
  config: SignalTeamConfig | null | undefined,
): DailyReportLimitStatus {
  const limit = config?.max_reports_per_day ?? null;
  const today = config?.reports_generated_today ?? 0;
  const reached = config?.daily_report_limit_reached ?? false;

  if (limit === null) {
    return {
      limit,
      today: 0,
      reached: false,
      usageText:
        "No daily limit. Reports reach Self-driving as they are found.",
      reachedText: null,
    };
  }

  return {
    limit,
    today,
    reached,
    usageText: `${today} of ${limit} report${limit === 1 ? "" : "s"} used today.`,
    reachedText: reached
      ? "Daily limit reached. New reports pause until midnight in the project's timezone."
      : null,
  };
}

/** The saved cap as text for the input field; empty string when unlimited. */
export function dailyReportLimitFieldValue(
  config: SignalTeamConfig | null | undefined,
): string {
  const limit = config?.max_reports_per_day ?? null;
  return limit === null ? "" : String(limit);
}
