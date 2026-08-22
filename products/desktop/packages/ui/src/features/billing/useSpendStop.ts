import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  type ActiveSpendStop,
  activeSpendStop,
} from "@posthog/core/billing/spendLimits";
import { useSpendTotals } from "@posthog/ui/features/billing/useSpendTotals";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

/**
 * The user's own stop line currently holding new agent work, or null. Null
 * also while spend data is unavailable: a stop must never engage on missing
 * data.
 */
export function useSpendStop(): ActiveSpendStop | null {
  const totals = useSpendTotals();
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  if (!totals) return null;
  return activeSpendStop(spendLimits, totals);
}

/** The composer tooltip while a stop line holds new messages. */
export function spendStopMessage(stop: ActiveSpendStop): string {
  const periodLabel = stop.period === "day" ? "Daily" : "Monthly";
  return `${periodLabel} spend passed your ${formatUsd(stop.limitUsd)} stop line. Raise or clear it in Plan & usage to continue.`;
}
