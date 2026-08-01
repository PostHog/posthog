import {
  ChartBarIcon,
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
import { trackAndCreateCanvas } from "@posthog/ui/features/canvas/createCanvasAnalytics";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
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
 * The same button on both panes, so "create" is always the same corner: given a
 * channel it creates inside it (task, canvas), and either way it can create a
 * channel — the list has no other entry point for that.
 */
export function ChannelsFab({ channelId }: { channelId?: string }) {
  const channelsLayout = useChannelsLayout();
  const [modalOpen, setModalOpen] = useState(false);
  const hasDraft = useDraftStore(
    (s) => !isContentEmpty(s.drafts["task-input"]),
  );
  const createAndOpenCanvas = useCreateAndOpenDashboard(channelId);
  // New task has no /website mirror yet, so it jumps back to Code unless we're
  // already in the Channels space — same rule as the nav's New task row.
  const inChannels = useRouterState({
    select: (s) => s.location.pathname.startsWith("/website"),
  });

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

  const trigger = (
    <Button
      variant="primary"
      size="icon-lg"
      aria-label="Create"
      className="absolute right-3 bottom-3 z-10 rounded-full shadow-lg"
    >
      <PlusIcon size={20} weight="bold" />
      {channelsLayout && hasDraft && (
        <span
          aria-hidden
          className="absolute top-0.5 right-0.5 size-2 rounded-full bg-current ring-(--primary) ring-2"
        />
      )}
    </Button>
  );

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger render={<DropdownMenuTrigger render={trigger} />} />
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
          {channelId && (
            <DropdownMenuItem
              onClick={() => {
                // Create + open a canvas with the default template directly;
                // the canvas's own composer drives what gets built.
                trackAndCreateCanvas(
                  channelId,
                  undefined,
                  "sidebar",
                  () => void createAndOpenCanvas(),
                );
              }}
            >
              <ChartBarIcon size={14} className="text-gray-9" />
              New canvas
            </DropdownMenuItem>
          )}
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
