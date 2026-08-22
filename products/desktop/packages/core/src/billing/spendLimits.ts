import type { SpendAnalysisDayRow } from "@posthog/api-client/spend-analysis";

/**
 * User-set spend lines for this app's personal LLM spend. `null` means the
 * line is off. Lines only inform: crossing one never pauses or blocks work.
 */
export interface SpendLimits {
  dailyWarnUsd: number | null;
  dailyStopUsd: number | null;
  monthlyWarnUsd: number | null;
  monthlyStopUsd: number | null;
}

export const EMPTY_SPEND_LIMITS: SpendLimits = {
  dailyWarnUsd: null,
  dailyStopUsd: null,
  monthlyWarnUsd: null,
  monthlyStopUsd: null,
};

export type SpendLimitLevel = "warn" | "stop";
export type SpendLimitPeriod = "day" | "month";

export interface SpendLimitCrossing {
  period: SpendLimitPeriod;
  level: SpendLimitLevel;
  limitUsd: number;
  spentUsd: number;
  /** `YYYY-MM-DD` for daily crossings, `YYYY-MM` for monthly ones. */
  anchor: string;
}

export function hasAnySpendLimit(limits: SpendLimits): boolean {
  return (
    limits.dailyWarnUsd !== null ||
    limits.dailyStopUsd !== null ||
    limits.monthlyWarnUsd !== null ||
    limits.monthlyStopUsd !== null
  );
}

export interface SpendTotals {
  todayUsd: number;
  monthUsd: number;
}

/** The UTC calendar day (`YYYY-MM-DD`) the spend endpoint's rows align to. */
export function utcDayIso(date: Date = new Date()): string {
  return date.toISOString().slice(0, 10);
}

/**
 * Mean spend per calendar day over the fetched window, zero days included,
 * so the average reflects how the person actually spends across a week.
 */
export function averageDailySpend(
  days: Pick<SpendAnalysisDayRow, "cost_usd">[],
  windowDays: number,
): number {
  if (windowDays <= 0) return 0;
  const total = days.reduce((sum, row) => sum + Math.max(0, row.cost_usd), 0);
  return total / windowDays;
}

/**
 * Month total the current 30-day average pace lands on: average per day
 * times the number of days in `todayIso`'s UTC month. A pace estimate, so
 * copy that shows it must frame it as approximate.
 */
export function projectedMonthUsd(
  avgDailyUsd: number,
  todayIso: string,
): number {
  const year = Number(todayIso.slice(0, 4));
  const month = Number(todayIso.slice(5, 7));
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return avgDailyUsd * daysInMonth;
}

/**
 * Nearest 1/2/5 × 10^k, so suggested lines land on round numbers and the
 * warn/stop pair never rounds onto near-identical values.
 */
export function niceRound(value: number): number {
  if (value <= 0) return 0;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  const candidates = [1, 2, 5, 10].map((m) => m * base);
  return candidates.reduce((best, candidate) =>
    Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best,
  );
}

/**
 * Starting lines derived from the user's own history: the warning sits near
 * a busy day, the stop well above one, and the monthly pair frames the
 * current pace. Null without history to derive them from.
 */
export function suggestedSpendLimits(
  avgDailyUsd: number,
  todayIso: string,
): SpendLimits | null {
  if (avgDailyUsd <= 0) return null;
  const projected = projectedMonthUsd(avgDailyUsd, todayIso);
  return {
    dailyWarnUsd: niceRound(avgDailyUsd * 1.5),
    dailyStopUsd: niceRound(avgDailyUsd * 3),
    monthlyWarnUsd: niceRound(projected * 1.25),
    monthlyStopUsd: niceRound(projected * 2),
  };
}

/**
 * Today's and this month's spend from the endpoint's UTC day rows. Rows are
 * UTC-day aligned, so `todayIso` must be the UTC date (`YYYY-MM-DD`).
 */
export function spendTotalsFromDays(
  days: Pick<SpendAnalysisDayRow, "day" | "cost_usd">[],
  todayIso: string,
): SpendTotals {
  const monthPrefix = todayIso.slice(0, 7);
  let todayUsd = 0;
  let monthUsd = 0;
  for (const row of days) {
    if (row.day === todayIso) todayUsd += row.cost_usd;
    if (row.day.startsWith(monthPrefix)) monthUsd += row.cost_usd;
  }
  return { todayUsd, monthUsd };
}

/**
 * Which lines the current totals sit past. At most one crossing per period:
 * the stop line supersedes the warn line so a single spike never stacks two
 * notices for the same period.
 */
export function evaluateSpendLimits(
  limits: SpendLimits,
  totals: SpendTotals,
  todayIso: string,
): SpendLimitCrossing[] {
  const crossings: SpendLimitCrossing[] = [];
  const day = pickCrossing(
    "day",
    limits.dailyWarnUsd,
    limits.dailyStopUsd,
    totals.todayUsd,
    todayIso,
  );
  if (day) crossings.push(day);
  const month = pickCrossing(
    "month",
    limits.monthlyWarnUsd,
    limits.monthlyStopUsd,
    totals.monthUsd,
    todayIso.slice(0, 7),
  );
  if (month) crossings.push(month);
  return crossings;
}

function pickCrossing(
  period: SpendLimitPeriod,
  warnUsd: number | null,
  stopUsd: number | null,
  spentUsd: number,
  anchor: string,
): SpendLimitCrossing | null {
  if (stopUsd !== null && stopUsd > 0 && spentUsd >= stopUsd) {
    return { period, level: "stop", limitUsd: stopUsd, spentUsd, anchor };
  }
  if (warnUsd !== null && warnUsd > 0 && spentUsd >= warnUsd) {
    return { period, level: "warn", limitUsd: warnUsd, spentUsd, anchor };
  }
  return null;
}

export interface ActiveSpendStop {
  period: SpendLimitPeriod;
  limitUsd: number;
  spentUsd: number;
}

/**
 * The stop line currently holding new agent work, if any. The daily line
 * wins when both are crossed since it resets first.
 */
export function activeSpendStop(
  limits: SpendLimits,
  totals: SpendTotals,
): ActiveSpendStop | null {
  const { dailyStopUsd, monthlyStopUsd } = limits;
  if (
    dailyStopUsd !== null &&
    dailyStopUsd > 0 &&
    totals.todayUsd >= dailyStopUsd
  ) {
    return { period: "day", limitUsd: dailyStopUsd, spentUsd: totals.todayUsd };
  }
  if (
    monthlyStopUsd !== null &&
    monthlyStopUsd > 0 &&
    totals.monthUsd >= monthlyStopUsd
  ) {
    return {
      period: "month",
      limitUsd: monthlyStopUsd,
      spentUsd: totals.monthUsd,
    };
  }
  return null;
}

/**
 * Dedupe key for a crossing notice. Includes the limit value so raising a
 * line re-arms the notice at the new amount within the same period.
 */
export function spendLimitNoticeKey(crossing: SpendLimitCrossing): string {
  return `${crossing.period}:${crossing.level}:${crossing.anchor}:${crossing.limitUsd}`;
}

/**
 * Drops seen-notice entries from past months so the persisted map stays
 * small. Daily anchors (`YYYY-MM-DD`) and monthly anchors (`YYYY-MM`) both
 * start with the month prefix.
 */
export function pruneSpendNoticesSeen(
  seen: Record<string, string>,
  todayIso: string,
): Record<string, string> {
  const monthPrefix = todayIso.slice(0, 7);
  const pruned: Record<string, string> = {};
  for (const [key, anchor] of Object.entries(seen)) {
    if (anchor.startsWith(monthPrefix)) pruned[key] = anchor;
  }
  return pruned;
}
