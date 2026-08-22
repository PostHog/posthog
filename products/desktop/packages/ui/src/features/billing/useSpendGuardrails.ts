import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  evaluateSpendLimits,
  hasAnySpendLimit,
  type SpendLimitCrossing,
  spendLimitNoticeKey,
  spendTotalsFromDays,
  utcDayIso,
} from "@posthog/core/billing/spendLimits";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  fetchSpendWindow,
  SPEND_TOTALS_QUERY_KEY,
} from "@posthog/ui/features/billing/useSpendTotals";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "../../primitives/toast";

const POLL_INTERVAL_MS = 5 * 60_000;

/**
 * Watches the user's personal spend in this app against their configured
 * spend lines and raises inform-only notices when a line is crossed. Never
 * pauses or blocks anything.
 */
export function useSpendGuardrails(): void {
  const client = useOptionalAuthenticatedClient();
  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const spendLimits = useSettingsStore((state) => state.spendLimits);
  const anyLimit = hasAnySpendLimit(spendLimits);

  const query = useQuery({
    queryKey: SPEND_TOTALS_QUERY_KEY,
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return fetchSpendWindow(client);
    },
    enabled: client !== null && spendAnalysisEnabled && anyLimit,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 60_000,
  });

  const days = query.data?.by_day?.items;

  useEffect(() => {
    if (!days) return;
    const todayIso = utcDayIso();
    const totals = spendTotalsFromDays(days, todayIso);
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
  }, [days, spendLimits]);
}

function showSpendNotice(crossing: SpendLimitCrossing): void {
  const periodLabel = crossing.period === "day" ? "Daily" : "Monthly";
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
