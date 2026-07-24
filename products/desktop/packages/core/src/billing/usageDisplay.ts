import type { UsageBucket, UsageOutput } from "../usage/schemas";

export const CODE_INCLUDED_USAGE_USD = 20;

/** Confirmed free tier only — an absent `code_usage_subscribed` is unknown, never free. */
export function isCodeUsageFreeTier(
  usage: Pick<UsageOutput, "code_usage_subscribed"> | null | undefined,
): boolean {
  return usage?.code_usage_subscribed === false;
}

export function codeOrgSpendLimitUsd(
  usage:
    | Pick<UsageOutput, "code_usage_subscribed" | "ai_credits">
    | null
    | undefined,
): number | null {
  if (usage?.code_usage_subscribed !== true) return null;
  const limitUsd = usage.ai_credits?.limit_usd;
  if (limitUsd == null || limitUsd < CODE_INCLUDED_USAGE_USD) return null;
  return Math.round((limitUsd - CODE_INCLUDED_USAGE_USD) * 100) / 100;
}

export interface CodeUsageBreakdown {
  includedUsd: number;
  spendLimitUsd: number;
}

export type CodeUsageMeter =
  | {
      kind: "dollars";
      usedUsd: number;
      limitUsd: number;
      percent: number;
      exceeded: boolean;
      resetAt: string;
      breakdown: CodeUsageBreakdown | null;
    }
  | { kind: "bucket"; bucket: UsageBucket }
  | { kind: "hidden" };

/**
 * What the usage meter should show. Billing's org-level dollars win when
 * present; a free-tier org without them falls back to its per-user valve
 * bucket; anything else shows nothing — per-user valve percentages are
 * meaningless for a subscribed org, and unknown must not render as free.
 */
export function codeUsageMeter(
  usage: UsageOutput | null | undefined,
): CodeUsageMeter {
  if (!usage) return { kind: "hidden" };
  const usedUsd = usage.ai_credits?.used_usd;
  const limitUsd = usage.ai_credits?.limit_usd;
  if (usedUsd != null && limitUsd != null && limitUsd > 0) {
    const spendLimitUsd = codeOrgSpendLimitUsd(usage);
    return {
      kind: "dollars",
      usedUsd,
      limitUsd,
      percent: Math.min(100, Math.round((usedUsd / limitUsd) * 100)),
      exceeded: usage.ai_credits?.exhausted === true,
      resetAt: usage.billing_period_end ?? usage.sustained.reset_at,
      breakdown:
        spendLimitUsd != null
          ? { includedUsd: CODE_INCLUDED_USAGE_USD, spendLimitUsd }
          : null,
    };
  }
  if (isCodeUsageFreeTier(usage)) {
    return { kind: "bucket", bucket: usage.sustained };
  }
  return { kind: "hidden" };
}

export function formatUsdAmount(amount: number): string {
  return Number.isInteger(amount) ? `$${amount}` : `$${amount.toFixed(2)}`;
}

export function formatUsageBreakdown(breakdown: CodeUsageBreakdown): string {
  return `${formatUsdAmount(breakdown.includedUsd)} included + ${formatUsdAmount(breakdown.spendLimitUsd)} org spend limit`;
}

export function isUsageExceeded(usage: UsageOutput): boolean {
  return (
    usage.is_rate_limited || usage.sustained.exceeded || usage.burst.exceeded
  );
}

export function formatResetTime(
  resetAtIso: string,
  { now = Date.now(), label = "Resets" }: { now?: number; label?: string } = {},
): string {
  const parsed = Date.parse(resetAtIso);
  const ms = Number.isNaN(parsed) ? 0 : Math.max(0, parsed - now);

  const totalMinutes = Math.ceil(ms / 60_000);
  if (totalMinutes <= 0) return `${label} shortly`;
  if (totalMinutes < 60) return `${label} in ${totalMinutes}m`;

  const totalHours = ms / 3_600_000;
  if (totalHours < 24) {
    let hours = Math.floor(totalHours);
    let minutes = Math.round((totalHours - hours) * 60);
    if (minutes === 60) {
      hours += 1;
      minutes = 0;
    }
    return minutes === 0
      ? `${label} in ${hours}h`
      : `${label} in ${hours}h ${minutes}m`;
  }

  const target = new Date(now + ms);
  const date = target.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const time = target.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return `${label} ${date} at ${time}`;
}
