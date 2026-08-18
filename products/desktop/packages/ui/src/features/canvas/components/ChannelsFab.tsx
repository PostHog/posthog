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
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useRouterState } from "@tanstack/react-router";
import { useState } from "react";

/**
 * The create affordance for the Channels space, floated over the bottom-right
 * of whichever sidebar pane is showing.
 *
 * Under the layout it serves the channel list only, where creating a channel
 * has no other entry point — inside a space the list leads with its own create
 * row instead. Off the layout it keeps its original two-item menu on both
 * panes.
 */
export function ChannelsFab({ channelId }: { channelId?: string }) {
  const channelsLayout = useChannelsLayout();
  const [modalOpen, setModalOpen] = useState(false);
  const hasDraft = useDraftStore(
    (s) => !isContentEmpty(s.drafts["task-input"]),
  );
  // New task has no /website mirror yet, so it jumps back to Code unless we're
  // already in the Channels space — same rule as the nav's New task row.
  const inChannels = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });

  // Inside a space the list's own create row does this job, in the tab of the
  // thing it makes, so a second create floating over those rows is one too many.
  if (channelsLayout && channelId) return null;

  const newTask = () => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "new_task_open",
      surface: "sidebar",
      channel_id: channelId,
    });
    // In a channel the task is filed there; from the list it's whatever the
    // space defaults to.
    if (channelId) {
      openTaskInput({ channelId });
      return;
    }
    openTaskInput(inChannels ? { space: "website" } : undefined);
  };

  const newChannelItem = (
    <DropdownMenuItem onClick={() => setModalOpen(true)}>
      {channelsLayout ? <CubeIcon size={14} /> : <HashIcon size={14} />}
      {channelsLayout ? "New space" : "New channel"}
    </DropdownMenuItem>
  );

  const draftDot = channelsLayout && hasDraft && (
    <span
      aria-hidden
      className="absolute top-0.5 right-0.5 size-2 rounded-full bg-current ring-(--primary) ring-2"
    />
  );

  const trigger = (
    <Button
      variant="primary"
      size="icon-lg"
      aria-label="Create"
      className="absolute right-3 bottom-3 z-10 rounded-full"
    >
      <PlusIcon size={20} weight="bold" />
      {draftDot}
    </Button>
  );

  const tooltip = (
    <TooltipContent side="top" align="center">
      {channelsLayout ? (
        <>
          {/* The draft dot needs saying out loud, and the button is where
              the create shortcut is worth advertising. */}
          {hasDraft ? "Create — you have a draft" : "Create"}
          <Kbd className="ml-1.5">{formatHotkey(SHORTCUTS.NEW_TASK)}</Kbd>
        </>
      ) : (
        "Create something new"
      )}
    </TooltipContent>
  );

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger render={<DropdownMenuTrigger render={trigger} />} />
          {tooltip}
        </Tooltip>
        <DropdownMenuContent
          align={channelId ? "end" : "center"}
          side="top"
          sideOffset={6}
        >
          {/* Off the layout this is the list's only menu, and "New channel"
              has led it since it shipped — leave that alone. */}
          {!channelsLayout && newChannelItem}
          <DropdownMenuItem onClick={newTask}>
            <FileTextIcon size={14} className="text-gray-9" />
            New task
          </DropdownMenuItem>
          {/* Under the layout this button only serves the list, where a new
              space has no other entry point — but starting a session is the
              commoner errand, so it stays above the separator. */}
          {channelsLayout && (
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
