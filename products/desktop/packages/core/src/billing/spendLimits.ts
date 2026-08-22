import type { SpendAnalysisDayRow } from "@posthog/api-client/spend-analysis";

/**
 * User-set spend lines for this app's personal LLM spend. `null` means the
 * line is off. Lines only inform: crossing one never pauses or blocks work.
 */
export interface SpendLimits {
  dailyWarnUsd: number | null;
  dailyAlertUsd: number | null;
  monthlyWarnUsd: number | null;
  monthlyAlertUsd: number | null;
}

export const EMPTY_SPEND_LIMITS: SpendLimits = {
  dailyWarnUsd: null,
  dailyAlertUsd: null,
  monthlyWarnUsd: null,
  monthlyAlertUsd: null,
};

export type SpendLimitLevel = "warn" | "alert";
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
    limits.dailyAlertUsd !== null ||
    limits.monthlyWarnUsd !== null ||
    limits.monthlyAlertUsd !== null
  );
}

export interface SpendTotals {
  todayUsd: number;
  monthUsd: number;
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
 * the alert line supersedes the warn line so a single spike never stacks two
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
    limits.dailyAlertUsd,
    totals.todayUsd,
    todayIso,
  );
  if (day) crossings.push(day);
  const month = pickCrossing(
    "month",
    limits.monthlyWarnUsd,
    limits.monthlyAlertUsd,
    totals.monthUsd,
    todayIso.slice(0, 7),
  );
  if (month) crossings.push(month);
  return crossings;
}

function pickCrossing(
  period: SpendLimitPeriod,
  warnUsd: number | null,
  alertUsd: number | null,
  spentUsd: number,
  anchor: string,
): SpendLimitCrossing | null {
  if (alertUsd !== null && alertUsd > 0 && spentUsd >= alertUsd) {
    return { period, level: "alert", limitUsd: alertUsd, spentUsd, anchor };
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
