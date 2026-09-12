import {
  CubeIcon,
  FileTextIcon,
  HashIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { isContentEmpty } from "@posthog/ui/features/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { isTaskInputSessionId } from "@posthog/ui/features/task-detail/taskInputSession";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";

/**
 * The create button. Given a channel it creates inside it (task, canvas); from
 * the list it creates a channel, which has no other entry point.
 *
 * On the spaces layout it sits in the nav rail (`placement="rail"`), which
 * every destination keeps on screen whether or not it draws a sidebar. Off the
 * layout it floats over the bottom-right of the channel list.
 */
export function ChannelsFab({
  channelId,
  placement = "floating",
}: {
  channelId?: string;
  placement?: "floating" | "rail";
}) {
  const channelsLayout = useChannelsLayout();
  const inRail = placement === "rail";
  const [modalOpen, setModalOpen] = useState(false);
  const hasDraft = useDraftStore((state) =>
    Object.entries(state.drafts).some(
      ([sessionId, draft]) =>
        isTaskInputSessionId(sessionId) && !isContentEmpty(draft),
    ),
  );

  const newTask = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: inRail ? "nav" : "sidebar",
      channel_id: channelId,
    });
    // In a channel the task is filed there; from the list it's whatever the
    // space defaults to.
    if (channelId) {
      openTaskInput({ channelId });
      return;
    }
    openTaskInput();
  };

  const newChannelItem = (
    <DropdownMenuItem onClick={() => setModalOpen(true)}>
      {channelsLayout ? <CubeIcon size={14} /> : <HashIcon size={14} />}
      {channelsLayout ? "New space" : "New channel"}
    </DropdownMenuItem>
  );

  // Inside a space on the layout, the menu held one item, so the button is that
  // item: a click starts the task instead of asking which kind to start.
  const newTaskOnly = channelsLayout && !!channelId;

  const draftDot = channelsLayout && hasDraft && (
    <span
      aria-hidden
      className="absolute top-0.5 right-0.5 size-2 rounded-full bg-current ring-(--primary) ring-2"
    />
  );

  const label = newTaskOnly ? "New task" : "Create";

  const trigger = (
    <Button
      variant="primary"
      size={inRail ? "icon" : "icon-lg"}
      aria-label={label}
      className={
        inRail
          ? "shrink-0 rounded-full"
          : "absolute right-3 bottom-3 z-10 rounded-full"
      }
      onClick={newTaskOnly ? newTask : undefined}
    >
      <PlusIcon size={inRail ? 16 : 20} weight="bold" />
      {draftDot}
    </Button>
  );

  const tooltip = (
    <TooltipContent side={inRail ? "right" : "top"} align="center">
      {channelsLayout ? (
        <>
          {/* The draft dot needs saying out loud, and the button is where
              the create shortcut is worth advertising. */}
          {hasDraft ? `${label} — you have a draft` : label}
          <Kbd>{formatHotkey(SHORTCUTS.NEW_TASK)}</Kbd>
        </>
      ) : (
        "Create something new"
      )}
    </TooltipContent>
  );

  if (newTaskOnly) {
    return (
      <Tooltip>
        <TooltipTrigger render={trigger} />
        {tooltip}
      </Tooltip>
    );
  }

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger render={<DropdownMenuTrigger render={trigger} />} />
          {tooltip}
        </Tooltip>
        <DropdownMenuContent
          align={inRail || channelId ? "end" : "center"}
          side={inRail ? "right" : "top"}
          sideOffset={6}
        >
          {/* Off the layout this is the list's only menu, and "New channel"
              has led it since it shipped — leave that alone. */}
          {!channelsLayout && newChannelItem}
          <DropdownMenuItem onClick={newTask}>
            <FileTextIcon size={14} className="text-gray-9" />
            New task
          </DropdownMenuItem>
          {/* Inside a space the menu is about filling that space; making
              another one belongs to the list this button also serves. */}
          {channelsLayout && !channelId && (
            <>
              <DropdownMenuSeparator />
              {newChannelItem}
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <CreateChannelModal open={modalOpen} onOpenChange={setModalOpen} />
    </>
  );
}
