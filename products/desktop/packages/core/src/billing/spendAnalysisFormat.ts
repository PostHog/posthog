import type { SpendAnalysisDayRow } from "./spendAnalysisTypes";

export function formatUsd(amount: number): string {
  if (amount === 0) return "$0";
  if (amount < 0.01) return "<$0.01";
  if (amount < 100) return `$${amount.toFixed(2)}`;
  return `$${Math.round(amount).toLocaleString()}`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return n.toString();
}

export type SpendAnalysisWindow = "7d" | "30d" | "90d";

// Day-aligned (`dStart`) so an N-day window resolves to exactly N UTC calendar
// days including today, giving the daily chart exactly N bars.
export function windowToDateFrom(window: SpendAnalysisWindow): string {
  return `-${windowToDays(window) - 1}dStart`;
}

export function windowToDays(window: SpendAnalysisWindow): number {
  return Number.parseInt(window, 10);
}

export function windowDays(fromIso: string, toIso: string): number {
  const fromMs = new Date(fromIso).getTime();
  const toMs = new Date(toIso).getTime();
  // Ceil: a day-aligned window ending mid-day still covers N calendar days.
  return Math.max(1, Math.ceil((toMs - fromMs) / DAY_MS));
}

export function formatWindow(fromIso: string, toIso: string): string {
  return `${windowDays(fromIso, toIso)} days`;
}

const DAY_MS = 86_400_000;
const MAX_FILLED_DAYS = 100;

export interface SpendAnalysisFilledDay {
  day: string;
  event_count: number;
  cost_usd: number;
}

export function fillSpendDays(
  items: SpendAnalysisDayRow[],
  fromIso: string,
  toIso: string,
): SpendAnalysisFilledDay[] {
  const byDay = new Map(items.map((row) => [row.day, row]));
  const from = new Date(fromIso);
  const start = Date.UTC(
    from.getUTCFullYear(),
    from.getUTCMonth(),
    from.getUTCDate(),
  );
  const end = new Date(toIso).getTime();
  const filled: SpendAnalysisFilledDay[] = [];
  for (
    let t = start;
    t <= end && filled.length < MAX_FILLED_DAYS;
    t += DAY_MS
  ) {
    const day = new Date(t).toISOString().slice(0, 10);
    const row = byDay.get(day);
    filled.push({
      day,
      event_count: row?.event_count ?? 0,
      cost_usd: row?.cost_usd ?? 0,
    });
  }
  return filled;
}
