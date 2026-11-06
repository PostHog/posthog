import type { TaskUsage } from "@posthog/api-client/posthog-client";
import {
  CONTEXT_CATEGORIES,
  formatCostUsd,
  formatTokensCompact,
  getOverallUsageColor,
} from "@posthog/ui/features/sessions/contextColors";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";

interface ContextBreakdownPopoverProps {
  usage: ContextUsage;
  taskUsage?: TaskUsage;
}

export function ContextBreakdownPopover({
  usage,
  taskUsage,
}: ContextBreakdownPopoverProps) {
  const { used, size, percentage, breakdown } = usage;
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

      {taskUsage && (
        <div className="border-border border-t pt-2.5">
          <div className="overflow-hidden rounded-md border border-border/70 bg-muted/20">
            <div className="flex items-center justify-between gap-6 px-2.5 py-1.5">
              <span className="font-medium text-[11px] text-muted-foreground">
                Estimated cost
              </span>
              <span className="font-semibold text-[15px] text-foreground tabular-nums leading-none">
                {formatCostUsd(taskUsage.total_cost_usd)}
              </span>
            </div>
            <div className="grid grid-cols-2 border-border/70 border-t bg-background/40">
              <CostDetail label="Tokens" value={taskUsage.token_cost_usd} />
              <CostDetail
                label="Cloud compute"
                value={taskUsage.compute_cost_usd}
                divided
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CostDetail({
  label,
  value,
  divided = false,
}: {
  label: string;
  value: number;
  divided?: boolean;
}) {
  return (
    <div
      className={`flex min-w-0 flex-col px-2.5 py-1.5 ${divided ? "border-border/70 border-l" : ""}`}
    >
      <span className="truncate text-[10px] text-muted-foreground">
        {label}
      </span>
      <span className="font-medium text-[12px] text-foreground tabular-nums">
        {formatCostUsd(value)}
      </span>
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
