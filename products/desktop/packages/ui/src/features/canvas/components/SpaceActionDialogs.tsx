import {
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  AlertDialog as ConfirmDialog,
} from "@posthog/quill";
import { AutoArchiveSettingsDialog } from "@posthog/ui/features/canvas/components/AutoArchiveSettingsDialog";
import type { useChannelActions } from "@posthog/ui/features/canvas/components/ChannelsList";
import { RenameChannelModal } from "@posthog/ui/features/canvas/components/RenameChannelModal";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMountedOnceOpened } from "@posthog/ui/hooks/useMountedOnceOpened";
import type { ReactElement } from "react";

export function SpaceActionDialogs({
  channel,
  noun,
  actions,
}: {
  channel: Channel;
  noun: string;
  actions: ReturnType<typeof useChannelActions>;
}): ReactElement {
  const {
    renameOpen,
    setRenameOpen,
    confirmDeleteOpen,
    setConfirmDeleteOpen,
    confirmDelete,
    isDeleting,
    autoArchiveOpen,
    setAutoArchiveOpen,
    saveAutoArchive,
    isUpdatingAutoArchive,
  } = actions;
  const renameMounted = useMountedOnceOpened(renameOpen);

  return (
    <>
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
