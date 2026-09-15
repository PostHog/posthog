import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { PopoverContent } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";

interface ActivityHoverCardProps {
  onClose: () => void;
  onActivate?: (item: TaskActivityItem) => void;
  onReportActivate?: (report: SignalReport) => void;
  side?: "bottom" | "right";
}

export function ActivityHoverCard({
  onClose,
  onActivate,
  onReportActivate,
  side = "right",
}: ActivityHoverCardProps) {
  return (
    <PopoverContent
      side={side}
      align="start"
      sideOffset={8}
      className="max-h-[520px] w-[380px] gap-0 overflow-hidden p-0"
    >
      <ActivityFeedList
        onActivate={onActivate}
        onReportActivate={onReportActivate}
        onOpened={onClose}
        className="max-h-[520px]"
      />
    </PopoverContent>
  );
}
