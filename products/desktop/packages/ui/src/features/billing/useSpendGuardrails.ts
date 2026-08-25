import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  evaluateSpendLimits,
  type SpendLimitCrossing,
  spendLimitNoticeKey,
  spendPeriodLabel,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import { useSpendTotals } from "@posthog/ui/features/billing/useSpendTotals";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useEffect } from "react";
import { toast } from "../../primitives/toast";

/**
 * Watches the user's personal spend in this app against their configured
 * spend lines and raises a notice when a line is crossed.
 */
export function useSpendGuardrails(): void {
  const totals = useSpendTotals();
  const spendLimits = useSettingsStore((state) => state.spendLimits);

  useEffect(() => {
    if (!totals) return;
    const todayIso = utcDayIso();
    const crossings = evaluateSpendLimits(spendLimits, totals, todayIso);
    // Read seen-state imperatively: marking a notice seen must not re-run
    // this effect and re-evaluate the same fetch.
    const { spendNoticesSeen, markSpendNoticeSeen } =
      useSettingsStore.getState();
    for (const crossing of crossings) {
      const key = spendLimitNoticeKey(crossing);
      if (spendNoticesSeen[key]) continue;
      markSpendNoticeSeen(key, crossing.anchor, todayIso);
      showSpendNotice(crossing);
    }
  }, [totals, spendLimits]);
}

function showSpendNotice(crossing: SpendLimitCrossing): void {
  const periodLabel = spendPeriodLabel(crossing.period);
  const windowLabel = crossing.period === "day" ? "today" : "this month";
  const description = `${formatUsd(crossing.spentUsd)} spent in this app ${windowLabel}. Nothing is paused.`;
  const action = {
    label: "View spend",
    onClick: () => openSettings("plan-usage"),
  };

  // Warning toasts self-dismiss; the stop notice stays until dismissed.
  // Neither is an error toast: nothing failed, the stop is the user's own.
  if (crossing.level === "stop") {
    toast.warning(
      `${periodLabel} spend passed your ${formatUsd(crossing.limitUsd)} stop line`,
      {
        id: `spend-limit-${crossing.period}-stop`,
        description: `New agent messages are paused until you raise or clear the line.`,
        action: { label: "Adjust limits", onClick: action.onClick },
        duration: Number.POSITIVE_INFINITY,
      },
    );
    return;
  }

  toast.warning(`${periodLabel} spend passed ${formatUsd(crossing.limitUsd)}`, {
    id: `spend-limit-${crossing.period}-warn`,
    description,
    action,
    duration: 12_000,
  });
}
