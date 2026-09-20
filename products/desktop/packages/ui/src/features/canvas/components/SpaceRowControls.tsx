import { PlusIcon } from "@phosphor-icons/react";
import {
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  ButtonGroup,
  AlertDialog as ConfirmDialog,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { AutoArchiveSettingsDialog } from "@posthog/ui/features/canvas/components/AutoArchiveSettingsDialog";
import {
  ChannelMenu,
  useChannelActions,
} from "@posthog/ui/features/canvas/components/ChannelsList";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useMountedOnceOpened } from "@posthog/ui/hooks/useMountedOnceOpened";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";

/**
 * The two controls a space row carries: start a session in it, and everything
 * else behind a menu. Shared, because the Work column and the legacy channels
 * list are two lists of the same row and a space must offer the same actions
 * from either.
 *
 * The dialogs the menu opens live here too — rename, delete and auto-archive
 * are the menu's own follow-ups, and a caller should not have to mount three
 * of them to get a menu.
 */
export function SpaceRowControls({ channel }: { channel: Channel }) {
  const spacesLayout = useChannelsLayout();
  const noun = spacesLayout ? "space" : "channel";
  const [menuOpen, setMenuOpen] = useState(false);
  const {
    actions,
    autoArchiveOpen,
    setAutoArchiveOpen,
    saveAutoArchive,
    isUpdatingAutoArchive,
    renameOpen,
    setRenameOpen,
    confirmDeleteOpen,
    setConfirmDeleteOpen,
    confirmDelete,
    isDeleting,
  } = useChannelActions(channel);
  const renameMounted = useMountedOnceOpened(renameOpen);

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
      {/* One modal for both the dropdown and context-menu "Rename" actions. */}
      {renameMounted && (
        <RenameChannelModal
          channel={channel}
          open={renameOpen}
          onOpenChange={setRenameOpen}
        />
      )}
      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {channel.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the {noun} and can’t be undone.
              <ul className="list-disc ps-4">
                <li>
                  The {noun} and its{" "}
                  <span className="font-medium">CONTEXT.md</span> are deleted.
                </li>
                <li>
                  Every canvas saved in this {noun} is permanently deleted.
                </li>
                <li>
                  Filed tasks are removed from the {noun}, but the tasks
                  themselves are not deleted.
                </li>
              </ul>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="primary"
              loading={isDeleting}
              onClick={() =>
                void confirmDelete().then((ok) => {
                  if (ok) setConfirmDeleteOpen(false);
                })
              }
            >
              Delete {noun}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </ConfirmDialog>
      <AutoArchiveSettingsDialog
        channel={channel}
        open={autoArchiveOpen}
        onOpenChange={setAutoArchiveOpen}
        onSave={saveAutoArchive}
        isSaving={isUpdatingAutoArchive}
      />
    </>
  );
}
