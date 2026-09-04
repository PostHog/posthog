import { WarningIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import {
  BOARD_BUSY_HINT,
  BOARD_BUSY_TITLE,
  BOARD_START_ACTION,
  BOARD_STOP_ACTION,
  BOARD_STOPPED_HINT,
  BOARD_STOPPED_TITLE,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import type { BoardFrameHealth } from "@posthog/ui/features/canvas-v2/components/BoardFrame";
import type { ReactElement } from "react";

interface BoardHealthNoticeProps {
  health: BoardFrameHealth;
  stopped: boolean;
  onStop: () => void;
  onStart: () => void;
}

export function BoardHealthNotice({
  health,
  stopped,
  onStop,
  onStart,
}: BoardHealthNoticeProps): ReactElement | null {
  if (!stopped && health === "running") return null;

  const title = stopped ? BOARD_STOPPED_TITLE : BOARD_BUSY_TITLE;
  const hint = stopped ? BOARD_STOPPED_HINT : BOARD_BUSY_HINT;

  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-30 flex justify-center">
      <div className="pointer-events-auto flex max-w-[min(92%,30rem)] items-start gap-2.5 rounded-lg border border-(--gray-6) bg-(--gray-1) px-3.5 py-2.5 shadow-lg">
        <WarningIcon
          weight="fill"
          className="mt-0.5 size-3.5 shrink-0 text-(--amber-9)"
        />
        <div className="min-w-0 space-y-1">
          <p className="font-medium text-(--gray-12) text-[12px]">{title}</p>
          <p className="text-(--gray-11) text-[12px]">{hint}</p>
        </div>
        <Button
          variant={stopped ? "primary" : "outline"}
          size="sm"
          className="ml-1 shrink-0"
          onClick={stopped ? onStart : onStop}
        >
          {stopped ? BOARD_START_ACTION : BOARD_STOP_ACTION}
        </Button>
      </div>
    </div>
  );
}
