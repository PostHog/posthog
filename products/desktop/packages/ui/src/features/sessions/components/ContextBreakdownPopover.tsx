import {
  CONTEXT_CATEGORIES,
  formatCostUsd,
  formatTokensCompact,
  getOverallUsageColor,
} from "@posthog/ui/features/sessions/contextColors";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";

interface ContextBreakdownPopoverProps {
  usage: ContextUsage;
  showCost?: boolean;
}

export function ContextBreakdownPopover({
  usage,
  showCost = false,
}: ContextBreakdownPopoverProps) {
  const { used, size, percentage, cost, breakdown } = usage;
  const fillColor = getOverallUsageColor(percentage);
  // The context window can be unknown (size 0) — show just the token count
  // rather than a misleading "~X / 0 tokens · 0% full".
  const hasSize = size > 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-6">
        <span className="font-medium text-[13px] text-foreground">Context</span>
        <span className="text-[12px] text-muted-foreground tabular-nums">
          {hasSize
            ? `~${formatTokensCompact(used)} / ${formatTokensCompact(size)} tokens`
            : `~${formatTokensCompact(used)} tokens`}
        </span>
      </div>

      {hasSize && (
        <span className="font-semibold text-[15px] text-foreground">
          {percentage}% full
        </span>
      )}

      {breakdown ? (
        <SegmentedBar breakdown={breakdown} size={size} fallback={fillColor} />
      ) : (
        <SinglePercentBar percentage={percentage} color={fillColor} />
      )}

      {breakdown && (
        <div className="flex flex-col gap-2">
          {CONTEXT_CATEGORIES.filter((c) => breakdown[c.key] > 0).map((cat) => (
            <div
              key={cat.key}
              className="flex items-center justify-between gap-6 text-[13px]"
            >
              <span className="flex items-center gap-2">
                <span
                  className="inline-block size-2.5 rounded-sm"
                  style={{ backgroundColor: cat.color }}
                />
                <span className="text-foreground">{cat.label}</span>
              </span>
              <span className="text-muted-foreground tabular-nums">
                {formatTokensCompact(breakdown[cat.key])}
              </span>
            </div>
          ))}
        </div>
      )}

      {!breakdown && usage.breakdownAvailable !== false && (
        <span className="text-[12px] text-muted-foreground">
          Detailed breakdown available after the first response.
        </span>
      )}

      {showCost && cost && (
        <div className="flex items-center justify-between border-border border-t pt-2 text-[13px]">
          <span className="text-muted-foreground">Estimated cost</span>
          <span className="font-medium text-foreground tabular-nums">
            {formatCostUsd(cost.amount)}
          </span>
        </div>
      )}
    </div>
  );
}

function SegmentedBar({
  breakdown,
  size,
  fallback,
}: {
  breakdown: NonNullable<ContextUsage["breakdown"]>;
  size: number;
  fallback: string;
}) {
  if (size <= 0) {
    return <div className="h-1.5 w-full rounded-full bg-muted" />;
  }

  // Scale each segment to the full context window so the filled portion
  // matches the "% full" figure and the empty track reads as remaining context.
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
      {CONTEXT_CATEGORIES.map((cat) => {
        const value = breakdown[cat.key];
        if (value <= 0) return null;
        return (
          <div
            key={cat.key}
            style={{
              width: `${(value / size) * 100}%`,
              backgroundColor: cat.color || fallback,
            }}
          />
        );
      })}
    </div>
  );
}

function SinglePercentBar({
  percentage,
  color,
}: {
  percentage: number;
  color: string;
}) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className="h-full rounded-full"
        style={{ width: `${percentage}%`, backgroundColor: color }}
      />
    </div>
  );
}
