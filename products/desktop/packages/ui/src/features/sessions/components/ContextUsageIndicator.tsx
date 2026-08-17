import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { TASK_COST_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  formatCostUsd,
  formatTokensCompact,
  getOverallUsageColor,
} from "@posthog/ui/features/sessions/contextColors";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Flex, Text } from "@radix-ui/themes";
import { ContextBreakdownPopover } from "./ContextBreakdownPopover";

const CIRCLE_SIZE = 20;
const STROKE_WIDTH = 2.5;
const RADIUS = (CIRCLE_SIZE - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

interface ContextUsageIndicatorProps {
  usage: ContextUsage | null;
}

export function ContextUsageIndicator({ usage }: ContextUsageIndicatorProps) {
  const costEnabled = useFeatureFlag(TASK_COST_FLAG) || import.meta.env.DEV;

  if (!usage) return null;

  const { used, size, percentage, cost } = usage;
  // The context window can be unknown (size 0) — show just the token count
  // rather than a misleading "X/0 · 0%".
  const hasSize = size > 0;
  const strokeDashoffset = CIRCUMFERENCE - (percentage / 100) * CIRCUMFERENCE;
  const color = getOverallUsageColor(percentage);
  // A null cost means the harness never reported one (codex), not that the
  // session was free, so there is nothing honest to render for it.
  const showCost = costEnabled && cost !== null;
  return (
    <Flex align="center" gap="1">
      <Popover>
        <PopoverTrigger
          render={
            <Button
              type="button"
              variant="default"
              size="icon-sm"
              // The ring carries no text, so the token figures reach a reader
              // only through the accessible name. Cost is excluded: it renders
              // as real text alongside, and would otherwise be read twice.
              aria-label={
                hasSize
                  ? `Context usage: ${percentage}%`
                  : `Context usage: ${formatTokensCompact(used)} tokens`
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
          <ContextBreakdownPopover usage={usage} showCost={showCost} />
        </PopoverContent>
      </Popover>
      {showCost && cost && (
        <Text className="select-none font-medium text-[13px] text-gray-11 tabular-nums">
          {formatCostUsd(cost.amount)}
        </Text>
      )}
    </Flex>
  );
}
