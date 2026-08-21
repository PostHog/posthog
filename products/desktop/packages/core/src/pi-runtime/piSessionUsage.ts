import type { PiSessionStats } from "@posthog/agent/pi/types";
import type { ContextUsage } from "../sessions/contextUsage";

export function toPiContextUsage(
  stats: PiSessionStats | undefined,
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
    cost: stats.cost > 0 ? { amount: stats.cost, currency: "USD" } : null,
    breakdown: null,
    breakdownAvailable: false,
  };
}
