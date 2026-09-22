import { PlusIcon } from "@phosphor-icons/react";
import {
  Button,
  ButtonGroup,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  ChannelMenu,
  useChannelActions,
} from "@posthog/ui/features/canvas/components/ChannelsList";
import { SpaceActionDialogs } from "@posthog/ui/features/canvas/components/SpaceActionDialogs";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";

export function SpaceRowControls({ channel }: { channel: Channel }) {
  const spacesLayout = useChannelsLayout();
  const noun = spacesLayout ? "space" : "channel";
  const [menuOpen, setMenuOpen] = useState(false);
  const channelActions = useChannelActions(channel);
  const { actions } = channelActions;

  const newTask = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: "sidebar",
      channel_id: channel.id,
    });
    openTaskInput({ channelId: channel.id });
  };

  return (
    <>
      <div className="absolute top-1 right-1">
        <ButtonGroup>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="outline"
                  size="icon-xs"
                  aria-label={`New session in ${channel.name}`}
                  className={cn(
                    "gap-1 transition-opacity group-hover:border-border",
                    menuOpen
                      ? "opacity-100"
                      : "opacity-0 group-hover/chan:opacity-100",
                  )}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    newTask();
                  }}
                >
                  <PlusIcon size={12} weight="bold" />
                </Button>
              }
            />
            <TooltipContent side="top">New session</TooltipContent>
          </Tooltip>
          <ChannelMenu
            channelName={channel.name}
            actions={actions}
            open={menuOpen}
            onOpenChange={setMenuOpen}
          />
        </ButtonGroup>
      </div>

      <SpaceActionDialogs
        channel={channel}
        noun={noun}
        actions={channelActions}
      />
    </>
  );
}
