import { formatUsd } from "@posthog/core/billing/spendAnalysisFormat";
import {
  evaluateSpendLimits,
  hasAnySpendLimit,
  type SpendLimitCrossing,
  spendLimitNoticeKey,
  spendTotalsFromDays,
} from "@posthog/core/billing/spendLimits";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "../../primitives/toast";

const POLL_INTERVAL_MS = 5 * 60_000;
// Matches the spend analysis page scope so lines and charts agree.
const CODE_PRODUCT = "posthog_code";
// 30 UTC calendar days including today: always covers the current month.
const DATE_FROM = "-29dStart";

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
    queryKey: ["billing", "spend-guardrails"],
    queryFn: () => {
      if (!client) throw new Error("Not authenticated");
      return client.getPersonalSpendAnalysis({
        dateFrom: DATE_FROM,
        product: CODE_PRODUCT,
      });
    },
    enabled: client !== null && spendAnalysisEnabled && anyLimit,
    refetchInterval: POLL_INTERVAL_MS,
    staleTime: 60_000,
  });

  const days = query.data?.by_day?.items;

  useEffect(() => {
    if (!days) return;
    const todayIso = new Date().toISOString().slice(0, 10);
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

  // Both levels are warnings, not errors: nothing failed and nothing stops.
  // The alert line stays on screen until dismissed; the warning self-dismisses.
  if (crossing.level === "alert") {
    toast.warning(
      `${periodLabel} spend passed your ${formatUsd(crossing.limitUsd)} alert line`,
      {
        id: `spend-limit-${crossing.period}-alert`,
        description,
        action,
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
