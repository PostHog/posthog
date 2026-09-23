type BlocksInterval = "hour" | "day" | "week" | "month";
type BlocksMath = "total" | "dau" | "weekly_active" | "monthly_active";

export const DATE_PRESETS: Array<{ value: string; label: string }> = [
  { value: "-24h", label: "Last 24 hours" },
  { value: "-7d", label: "Last 7 days" },
  { value: "-14d", label: "Last 14 days" },
  { value: "-30d", label: "Last 30 days" },
  { value: "-90d", label: "Last 90 days" },
  { value: "-180d", label: "Last 6 months" },
  { value: "-365d", label: "Last 12 months" },
  { value: "mStart", label: "This month" },
  { value: "yStart", label: "Year to date" },
  { value: "all", label: "All time" },
];

export const INTERVALS: Array<{ value: BlocksInterval; label: string }> = [
  { value: "hour", label: "Hour" },
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

export const MATH_OPTIONS: Array<{ value: BlocksMath; label: string }> = [
  { value: "total", label: "Total count" },
  { value: "dau", label: "Unique users" },
  { value: "weekly_active", label: "Weekly active users" },
  { value: "monthly_active", label: "Monthly active users" },
];

export function dateRangeLabel(value: string): string {
  return DATE_PRESETS.find((preset) => preset.value === value)?.label ?? value;
}

export function mathLabel(value: BlocksMath): string {
  return MATH_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function eventLabel(event: string): string {
  const known: Record<string, string> = {
    $pageview: "Pageview",
    $pageleave: "Pageleave",
    $autocapture: "Autocapture",
    $screen: "Screen",
    $identify: "Identify",
    $exception: "Exception",
    $web_vitals: "Web vitals",
    $feature_flag_called: "Feature flag called",
    $groupidentify: "Group identify",
    $set: "Set person properties",
  };
  if (known[event]) return known[event];
  if (!event.startsWith("$")) return event;
  const words = event.slice(1).replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const compact = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});
const full = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

export function formatCompact(value: number): string {
  if (Math.abs(value) < 10_000) return full.format(value);
  return compact.format(value);
}

export function formatFull(value: number): string {
  return full.format(value);
}

export function formatPercent(value: number): string {
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)}%`;
}

export function toNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }
  return Number.NaN;
}
