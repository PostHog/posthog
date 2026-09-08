import { Brain, Pause } from "@phosphor-icons/react";
import { Text } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import {
  formatDuration,
  GeneratingIndicator,
} from "@posthog/ui/features/sessions/components/GeneratingIndicator";
import type { ReactElement } from "react";
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
  /** A /clear is in flight. */
  isClearing?: boolean;
  /** A turn the agent started on its own, with no prompt RPC behind it, so
   *  `isPromptPending` stays false while it generates. */
  isBackgroundTurnActive?: boolean;
  turnStatus?: string | null;
  /** Timestamp (ms) of the newest event in the thread; the generating indicator
   *  says how long it has been since one arrived. */
  lastActivityAt?: number | null;
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
  isClearing = false,
  isBackgroundTurnActive = false,
  turnStatus,
  lastActivityAt,
}: SessionFooterProps): ReactElement {
  const rightSide = (
    <div className="ml-auto flex shrink-0 items-center gap-3">
      {task?.origin_product === "image_builder" && (
        <ImageBuilderBuildButton taskId={task.id} />
      )}
      {task && <DiffStatsChip task={task} />}
    </div>
  );
  if (
    (isPromptPending || isBackgroundTurnActive) &&
    !isCompacting &&
    !isClearing
  ) {
    if (hasPendingPermission) {
      return (
        <div className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
          <div className="flex items-center justify-between gap-2">
            <div
              className="flex min-w-0 select-none items-center gap-2 text-muted-foreground"
              style={{ WebkitUserSelect: "none" }}
            >
              <Pause size={14} weight="fill" className="shrink-0" />
              <Text className="truncate text-[13px] text-muted-foreground">
                Awaiting permission...
              </Text>
            </div>
            {rightSide}
          </div>
        </div>
      );
    }

    return (
      <div className="pt-3 pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <GeneratingIndicator
              startedAt={promptStartedAt}
              pausedDurationMs={pausedDurationMs}
              status={turnStatus}
              lastActivityAt={lastActivityAt}
            />
            {queuedCount > 0 && (
              <Text className="truncate text-[13px] text-muted-foreground">
                ({queuedCount} queued)
              </Text>
            )}
            <SlotMachineLever
              spinning={Boolean(isPromptPending || isBackgroundTurnActive)}
            />
          </div>
          {rightSide}
        </div>
      </div>
    );
  }

  const wasCancelled =
    lastStopReason === "cancelled" || lastStopReason === "refusal";

  const showDuration =
    lastGenerationDuration !== null &&
    lastGenerationDuration > 0 &&
    !wasCancelled;

  return (
    <div className="pb-1 opacity-50 transition-opacity group-hover/thread:opacity-100">
      <div className="flex items-center justify-between gap-2">
        {showDuration && (
          <div className="flex min-w-0 select-none items-center gap-2 text-muted-foreground">
            <Brain size={12} className="shrink-0" />
            <Text
              style={{ fontVariantNumeric: "tabular-nums" }}
              className="truncate text-[13px] text-muted-foreground"
            >
              Generated in {formatDuration(lastGenerationDuration)}
            </Text>
          </div>
        )}
        {rightSide}
      </div>
    </div>
  );
}
