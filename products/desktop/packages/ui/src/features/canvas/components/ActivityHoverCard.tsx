import { PopoverContent } from "@posthog/quill";
import { ActivityFeedList } from "@posthog/ui/features/canvas/components/ActivityFeedList";

interface ActivityHoverCardProps {
  onClose: () => void;
  side?: "bottom" | "right";
}

export function ActivityHoverCard({
  onClose,
  side = "right",
}: ActivityHoverCardProps) {
  return (
    <PopoverContent
      side={side}
      align="start"
      sideOffset={8}
      className="max-h-[520px] w-[380px] gap-0 overflow-hidden p-0"
    >
      <ActivityFeedList onOpened={onClose} className="max-h-[520px]" />
    </PopoverContent>
  );
}
