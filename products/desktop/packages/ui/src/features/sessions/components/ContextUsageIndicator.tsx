import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
} from "@posthog/quill";
import { TASK_COST_FLAG, TASK_COST_VISIBLE_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  formatCostUsd,
  formatTokensCompact,
  getOverallUsageColor,
} from "@posthog/ui/features/sessions/contextColors";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { useTaskUsage } from "@posthog/ui/features/sessions/hooks/useTaskUsage";
import { ContextBreakdownPopover } from "./ContextBreakdownPopover";

const CIRCLE_SIZE = 20;
const STROKE_WIDTH = 2.5;
const RADIUS = (CIRCLE_SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface ContextUsageIndicatorProps {
  usage: ContextUsage | null;
  taskId?: string;
  focused?: boolean;
}

export function ContextUsageIndicator({
  usage,
  taskId,
  focused = true,
}: ContextUsageIndicatorProps) {
  const costEnabled = useFeatureFlag(TASK_COST_FLAG) || import.meta.env.DEV;
  const costVisible = useFeatureFlag(TASK_COST_VISIBLE_FLAG);
  const { data: taskUsage } = useTaskUsage(taskId, costEnabled && focused);

  if (!usage) return null;

  const { used, size, percentage } = usage;
  // The context window can be unknown (size 0) — show just the token count
  // rather than a misleading "X/0 · 0%".
  const hasSize = size > 0;
  const strokeDashoffset = CIRCUMFERENCE - (percentage / 100) * CIRCUMFERENCE;
  const color = getOverallUsageColor(percentage);
  const showCost = costEnabled && taskUsage !== undefined;
  const showCostText = showCost && costVisible;
  // The ring carries no text, so the token figures reach a reader only through
  // the accessible name. Cost joins them only while it has no text of its own,
  // which would otherwise be announced twice.
  const costSuffix =
    showCost && !showCostText
      ? ` · ${formatCostUsd(taskUsage.total_cost_usd)}`
      : "";
  return (
    <div className="flex items-center gap-1">
      <Popover>
        <PopoverTrigger
          render={
            <Button
              type="button"
              variant="default"
              size="icon-sm"
              aria-label={
                hasSize
                  ? `Context usage: ${percentage}%${costSuffix}`
                  : `Context usage: ${formatTokensCompact(used)} tokens${costSuffix}`
              }
            >
              {/* viewBox, not width/height: quill sizes a button's svg down to
                  its icon slot, which would crop an unscaled drawing. */}
              <svg
                viewBox={`0 0 ${CIRCLE_SIZE} ${CIRCLE_SIZE}`}
                className="-rotate-90 size-4 shrink-0"
                role="img"
                aria-hidden="true"
              >
                <circle
                  cx={CIRCLE_SIZE / 2}
                  cy={CIRCLE_SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  stroke="var(--border)"
                  strokeWidth={STROKE_WIDTH}
                />
                <circle
                  cx={CIRCLE_SIZE / 2}
                  cy={CIRCLE_SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  stroke={color}
                  strokeWidth={STROKE_WIDTH}
                  strokeDasharray={CIRCUMFERENCE}
                  strokeDashoffset={strokeDashoffset}
                  strokeLinecap="round"
                />
              </svg>
            </Button>
          }
        />
        {/* quill's popup is a fixed 18rem; the token figures sit on their own
            line and would spill out of it. */}
        <PopoverContent
          side="top"
          align="end"
          sideOffset={6}
          className="w-auto min-w-[280px] gap-3"
        >
          <ContextBreakdownPopover usage={usage} taskUsage={taskUsage} />
        </PopoverContent>
      </Popover>
      {showCostText && (
        <Text className="select-none font-medium text-[13px] text-gray-11 tabular-nums">
          {formatCostUsd(taskUsage.total_cost_usd)}
        </Text>
      )}
    </div>
  );
}
