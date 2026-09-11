import { LinkIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import type { ReactElement } from "react";

// Header affordance on a canvas, beside its name the way a thread's copy button
// sits beside its title: the control acts on the leaf, so it rides with it
// rather than joining the actions at the far end of the bar.
export function CopyCanvasLinkButton({
  channelId,
  dashboardId,
}: {
  channelId: string;
  dashboardId: string;
}): ReactElement {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            size="icon-sm"
            aria-label="Copy link to canvas"
            className="no-drag"
            onClick={() =>
              void copyCanvasLink(channelId, dashboardId, "canvas")
            }
          >
            <LinkIcon size={14} />
          </Button>
        }
      />
      <TooltipContent side="bottom">Copy link to canvas</TooltipContent>
    </Tooltip>
  );
}
