import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  evaluateSpendLimits,
  type SpendLimitCrossing,
  spendPeriodLabel,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import { useSpendTotals } from "@posthog/ui/features/billing/useSpendTotals";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

/**
 * The user's own stop line currently holding new agent work, or null. Null
 * also while spend data is unavailable: a stop must never engage on missing
 * data. The daily line wins when both are crossed since it resets first.
 */
export function useSpendStop(): SpendLimitCrossing | null {
  const totals = useSpendTotals();
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  if (!totals) return null;
  return (
    evaluateSpendLimits(spendLimits, totals, utcDayIso()).find(
      (crossing) => crossing.level === "stop",
    ) ?? null
  );
}

/** The composer tooltip while a stop line holds new messages. */
export function spendStopMessage(
  stop: Pick<SpendLimitCrossing, "period" | "limitUsd">,
): string {
  return `${spendPeriodLabel(stop.period)} spend passed your ${formatUsd(stop.limitUsd)} stop line. Raise or clear it in Cost management to continue.`;
}
