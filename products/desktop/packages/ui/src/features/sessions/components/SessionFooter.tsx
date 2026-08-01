import { Brain, Pause } from "@phosphor-icons/react";
import type { Task } from "@posthog/shared/domain-types";
import { ContextUsageIndicator } from "@posthog/ui/features/sessions/components/ContextUsageIndicator";
import {
  formatDuration,
  GeneratingIndicator,
} from "@posthog/ui/features/sessions/components/GeneratingIndicator";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Box, Flex, Text } from "@radix-ui/themes";
import { DiffStatsChip } from "./DiffStatsChip";
import { ImageBuilderBuildButton } from "./ImageBuilderBuildButton";
import { SlotMachineLever } from "./SlotMachineLever";

interface SessionFooterProps {
  task?: Task;
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  lastGenerationDuration: number | null;
  lastStopReason?: string;
  queuedCount?: number;
  hasPendingPermission?: boolean;
  pausedDurationMs?: number;
  isCompacting?: boolean;
  usage?: ContextUsage | null;
  /** Number of tool calls finished so far; the generating indicator advances
   *  its status word each time this changes. */
  completedToolCallCount?: number;
}

export function SessionFooter({
  task,
  isPromptPending,
  promptStartedAt,
  lastGenerationDuration,
  lastStopReason,
  queuedCount = 0,
  hasPendingPermission = false,
  pausedDurationMs,
  isCompacting = false,
  usage,
  completedToolCallCount,
}: SessionFooterProps) {
  const rightSide = (
    <Flex align="center" gap="3" className="ml-auto shrink-0">
      {task?.origin_product === "image_builder" && (
        <ImageBuilderBuildButton taskId={task.id} />
      )}
      {task && <DiffStatsChip task={task} />}
      <ContextUsageIndicator usage={usage ?? null} />
    </Flex>
  );
  if (isPromptPending && !isCompacting) {
    if (hasPendingPermission) {
      return (
        <Box className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
          <Flex align="center" justify="between" gap="2">
            <Flex
              align="center"
              gap="2"
              className="min-w-0 select-none text-muted-foreground"
              style={{ WebkitUserSelect: "none" }}
            >
              <Pause size={14} weight="fill" className="shrink-0" />
              <Text className="truncate text-[13px] text-muted-foreground">
                Awaiting permission...
              </Text>
            </Flex>
            {rightSide}
          </Flex>
        </Box>
      );
    }

    return (
      <Box className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
        <Flex align="center" justify="between" gap="2">
          <Flex align="center" gap="2" className="min-w-0">
            <GeneratingIndicator
              startedAt={promptStartedAt}
              pausedDurationMs={pausedDurationMs}
              activityKey={completedToolCallCount}
            />
            {queuedCount > 0 && (
              <Text className="truncate text-[13px] text-muted-foreground">
                ({queuedCount} queued)
              </Text>
            )}
            <SlotMachineLever spinning={Boolean(isPromptPending)} />
          </Flex>
          {rightSide}
        </Flex>
      </Box>
    );
  }

  const wasCancelled =
    lastStopReason === "cancelled" || lastStopReason === "refusal";

  const showDuration =
    lastGenerationDuration !== null &&
    lastGenerationDuration > 0 &&
    !wasCancelled;

  return (
    <Box className="pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
      <Flex align="center" justify="between" gap="2">
        {showDuration && (
          <Flex
            align="center"
            gap="2"
            className="min-w-0 select-none text-muted-foreground"
          >
            <Brain size={12} className="shrink-0" />
            <Text
              style={{ fontVariantNumeric: "tabular-nums" }}
              className="truncate text-[13px] text-muted-foreground"
            >
              Generated in {formatDuration(lastGenerationDuration)}
            </Text>
          </Flex>
        )}
        {rightSide}
      </Flex>
    </Box>
  );
}
