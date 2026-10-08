import { XIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { clearActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";

export function ActivityDetailCloseButton() {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            className="no-drag shrink-0"
            aria-label="Close activity item"
            data-attr="activity-detail-close"
            onClick={clearActivitySelection}
          />
        }
      >
        <XIcon size={14} />
      </TooltipTrigger>
      <TooltipContent side="bottom">Close activity item</TooltipContent>
    </Tooltip>
  );
}
