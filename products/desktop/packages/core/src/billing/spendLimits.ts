import type { SpendAnalysisDayRow } from "@posthog/api-client/spend-analysis";

export type SpendLimitLevel = "warn" | "stop";
export type SpendLimitPeriod = "day" | "month";

/**
 * User-set spend lines for this app's personal LLM spend, per period. `null`
 * means the line is off. A warning line notifies; a stop line pauses new
 * agent messages until the line is raised or cleared.
 */
export type SpendLimits = Record<
  SpendLimitPeriod,
  { warnUsd: number | null; stopUsd: number | null }
>;

/** A per-period partial update to `SpendLimits`; omitted lines keep their value. */
export type SpendLimitsPatch = {
  [Period in SpendLimitPeriod]?: Partial<SpendLimits[Period]>;
};

export const EMPTY_SPEND_LIMITS: SpendLimits = {
  day: { warnUsd: null, stopUsd: null },
  month: { warnUsd: null, stopUsd: null },
};

/**
 * The same lines with every stop cleared. Used where the deployment cannot
 * hold a stop, so a stored stop value stays inert instead of engaging.
 */
export function maskStops(limits: SpendLimits): SpendLimits {
  return {
    day: { warnUsd: limits.day.warnUsd, stopUsd: null },
    month: { warnUsd: limits.month.warnUsd, stopUsd: null },
  };
}

export interface SpendLimitCrossing {
  period: SpendLimitPeriod;
  level: SpendLimitLevel;
  limitUsd: number;
  spentUsd: number;
  /** `YYYY-MM-DD` for daily crossings, `YYYY-MM` for monthly ones. */
  anchor: string;
}

/** The adjective copy uses for a period's lines and notices. */
export function spendPeriodLabel(period: SpendLimitPeriod): string {
  return period === "day" ? "Daily" : "Monthly";
}

/**
 * A typed spend amount, or null when the text is not one. Accepts a leading
 * `$` and thousands separators, since that is how the amount is displayed.
 */
export function parseSpendAmount(raw: string): number | null {
  const trimmed = raw.trim().replace(/[$,]/g, "");
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.round(parsed * 100) / 100;
}

/**
 * The gap between tick marks on a spend track. Anchored to a reference figure
 * so a tick means something in that scope's terms (roughly a day's average on
 * a daily track, a month's pace on a monthly one), then rounded to a 1/2/5
 * step and adjusted until the track carries between 6 and 12 of them: with
 * fewer, the knobs sit on top of most of the ticks.
 */
export function spendTickIncrement(
  scale: number,
  referenceUsd: number | null,
): number {
  if (scale <= 0) return 0;
  const seed =
    referenceUsd !== null && referenceUsd > 0 ? referenceUsd : scale / 8;
  let increment = niceRound(seed);
  if (increment <= 0) return 0;
  // Under 6 ticks does not read as a scale, over 12 crowds into a solid line.
  while (scale / increment > 12) increment *= 2;
  while (scale / increment < 6) increment /= 2;
  return increment;
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

/** The 1/2/5 × 10^k ladder both spend roundings land on. */
function spendLadder(value: number): number[] {
  const base = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 5, 10].map((m) => m * base);
}

/** Nearest rung, so suggested lines land on round numbers. */
function niceRound(value: number): number {
  if (value <= 0) return 0;
  return spendLadder(value).reduce((best, candidate) =>
    Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best,
  );
}

/** Smallest rung at or above `value`, so a track's end is round. */
export function niceCeil(value: number): number {
  if (value <= 0) return 100;
  return spendLadder(value).find((rung) => value <= rung * (1 + 1e-9)) ?? value;
}

/** Smallest ladder rung strictly greater than `value`. */
function nextSpendRung(value: number): number {
  if (value <= 0) return 1;
  const base = 10 ** Math.floor(Math.log10(value) + 1e-9);
  for (const rung of [1, 2, 5, 10, 20].map((m) => m * base)) {
    if (rung > value * (1 + 1e-9)) return rung;
  }
  return value * 2;
}

/**
 * A warn/stop pair on round rungs. The stop rounds on its own, then steps up
 * to the next rung when rounding would land it on or below the warn line.
 * Without this a seeded stop can equal the warn line, and `pickCrossing`
 * reports the stop first, so the warn notice would never fire.
 */
function suggestedLinePair(
  warnTarget: number,
  stopTarget: number,
): { warnUsd: number; stopUsd: number } {
  const warnUsd = niceRound(warnTarget);
  const stopUsd = niceRound(stopTarget);
  return {
    warnUsd,
    stopUsd: stopUsd > warnUsd ? stopUsd : nextSpendRung(warnUsd),
  };
}

/**
 * Starting lines derived from the user's own history: the warning sits near
 * a busy day, the stop well above one, and the monthly pair frames the
 * current pace. Null without history to derive them from.
 */
export function suggestedSpendLimits(
  avgDailyUsd: number,
  todayIso: string,
): Record<SpendLimitPeriod, { warnUsd: number; stopUsd: number }> | null {
  if (avgDailyUsd <= 0) return null;
  const projected = projectedMonthUsd(avgDailyUsd, todayIso);
  return {
    day: suggestedLinePair(avgDailyUsd * 1.5, avgDailyUsd * 3),
    month: suggestedLinePair(projected * 1.25, projected * 2),
  };
}

/**
 * Starting lines for a scope switched on before any history exists to derive
 * suggestions from. Round figures the person adjusts on the slider right
 * away, not a claim about their spend — without them, enabling a scope with
 * no history would commit two nulls and read as the switch refusing to turn
 * on.
 */
export const STARTER_SPEND_LINES: Record<
  SpendLimitPeriod,
  { warnUsd: number; stopUsd: number }
> = {
  day: { warnUsd: 20, stopUsd: 50 },
  month: { warnUsd: 200, stopUsd: 500 },
};

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
 * Which lines the current totals sit past, daily first since it resets
 * first. At most one crossing per period: the stop line supersedes the warn
 * line so a single spike never stacks two notices for the same period.
 */
export function evaluateSpendLimits(
  limits: SpendLimits,
  totals: SpendTotals,
  todayIso: string,
): SpendLimitCrossing[] {
  const crossings: SpendLimitCrossing[] = [];
  for (const period of ["day", "month"] as const) {
    const spentUsd = period === "day" ? totals.todayUsd : totals.monthUsd;
    const anchor = period === "day" ? todayIso : todayIso.slice(0, 7);
    const crossing = pickCrossing(period, limits[period], spentUsd, anchor);
    if (crossing) crossings.push(crossing);
  }
  return crossings;
}

function pickCrossing(
  period: SpendLimitPeriod,
  lines: SpendLimits[SpendLimitPeriod],
  spentUsd: number,
  anchor: string,
): SpendLimitCrossing | null {
  const { warnUsd, stopUsd } = lines;
  if (stopUsd !== null && stopUsd > 0 && spentUsd >= stopUsd) {
    return { period, level: "stop", limitUsd: stopUsd, spentUsd, anchor };
  }
  if (warnUsd !== null && warnUsd > 0 && spentUsd >= warnUsd) {
    return { period, level: "warn", limitUsd: warnUsd, spentUsd, anchor };
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
