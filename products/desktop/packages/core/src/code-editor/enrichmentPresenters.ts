import type { SerializedFlag } from "@posthog/shared";

export function compactNumber(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

export function relativeTime(iso: string | null): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMon = Math.round(diffDay / 30);
  if (diffMon < 12) return `${diffMon}mo ago`;
  return `${Math.round(diffMon / 12)}y ago`;
}

type Staleness = NonNullable<SerializedFlag["staleness"]>;

const STALENESS_LABELS: Record<Staleness, string> = {
  fully_rolled_out: "Fully rolled out",
  inactive: "Inactive",
  not_in_posthog: "Not in PostHog",
  experiment_complete: "Experiment complete",
};

export function stalenessLabel(staleness: Staleness): string {
  return STALENESS_LABELS[staleness];
}
