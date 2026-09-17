import type { PiUsageStats } from "@posthog/agent/pi/types";
import type { ContextUsage } from "../sessions/contextUsage";

export function toPiContextUsage(
  stats: PiUsageStats | undefined,
): ContextUsage | null {
  const usage = stats?.contextUsage;
  if (!usage || usage.tokens === null) {
    return null;
  }

  return {
    used: usage.tokens,
    size: usage.contextWindow,
    percentage: Math.round(
      usage.percent ??
        (usage.contextWindow > 0
          ? (usage.tokens / usage.contextWindow) * 100
          : 0),
    ),
    breakdown: null,
    breakdownAvailable: false,
  };
}
