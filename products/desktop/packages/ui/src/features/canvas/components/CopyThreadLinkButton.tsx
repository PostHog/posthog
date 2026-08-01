import { LinkIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";

// Header affordance on a thread (channel-filed task): copies the thread's
// shareable https link, which deep-links back into this exact thread.
export function CopyThreadLinkButton({
  channelId,
  taskId,
}: {
  channelId: string;
  taskId: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Copy link to thread"
            className="no-drag"
            onClick={() => void copyChannelLink(channelId, "title_bar", taskId)}
          >
            <LinkIcon size={14} />
          </Button>
        }
      />
      <TooltipContent side="bottom">Copy link to thread</TooltipContent>
    </Tooltip>
  );
}
