import { getRelativeDateGroup } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";

export interface ReportAgeGroup {
  label: string;
  reports: SignalReport[];
}

const AGE_ORDER = [
  "Today",
  "Yesterday",
  "This week",
  "This month",
  "Earlier",
] as const;

/**
 * The buckets widen with age (`getRelativeDateGroup`, the same ones the task
 * list uses) because reports arrive over weeks: a separator per calendar day
 * left most of this list one row per header.
 */
export function groupReportsByAge(
  reports: readonly SignalReport[],
  options: { now?: Date; oldestFirst?: boolean } = {},
): ReportAgeGroup[] {
  const now = options.now ?? new Date();
  const buckets = new Map<string, SignalReport[]>();
  for (const report of reports) {
    // A clock skewed ahead of ours would otherwise fall out of every bucket.
    const timestamp = Math.min(new Date(report.created_at).getTime(), +now);
    const label = getRelativeDateGroup(timestamp) ?? "Today";
    const bucket = buckets.get(label);
    if (bucket) bucket.push(report);
    else buckets.set(label, [report]);
  }
  // Oldest first means oldest first, so the buckets run the other way too.
  // Reading down the list otherwise contradicts the sort that built it.
  const order = options.oldestFirst ? [...AGE_ORDER].reverse() : AGE_ORDER;
  return order
    .filter((label) => buckets.has(label))
    .map((label) => ({ label, reports: buckets.get(label) ?? [] }));
}
