import { Folder } from "@phosphor-icons/react";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { useAddDirectoryDialogStore } from "@posthog/ui/features/folder-picker/addDirectoryDialogStore";
import { useEffect, useRef } from "react";

export function AddDirectoryDialog() {
  const trpcClient = useHostTRPCClient();
  const log = useService<RootLogger>(ROOT_LOGGER);
  const open = useAddDirectoryDialogStore((s) => s.open);
  const taskId = useAddDirectoryDialogStore((s) => s.taskId);
  const path = useAddDirectoryDialogStore((s) => s.path);
  const onCancel = useAddDirectoryDialogStore((s) => s.onCancel);
  const close = useAddDirectoryDialogStore((s) => s.close);

  const justThisChatRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const id = window.setTimeout(() => justThisChatRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  if (!path || !taskId) return null;

  const decideAndClose = async (
    action: () => unknown,
    errorMessage: string,
  ) => {
    try {
      await action();
    } catch (err) {
      log.error(errorMessage, err);
    } finally {
      close();
    }
  };

  const handleJustThisChat = () =>
    decideAndClose(
      () =>
        trpcClient.additionalDirectories.addForTask.mutate({ taskId, path }),
      "Failed to add directory for task",
    );

  const handleAlways = () =>
    decideAndClose(
      () =>
        Promise.all([
          trpcClient.additionalDirectories.addDefault.mutate({ path }),
          trpcClient.additionalDirectories.addForTask.mutate({ taskId, path }),
        ]),
      "Failed to add default directory",
    );

  const handleCancel = () =>
    decideAndClose(() => onCancel?.(), "Failed to remove chip");

  return (
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent className="!top-1/2 -translate-y-1/2 max-w-[480px] border border-(--gray-5) bg-(--gray-2) sm:max-w-[480px]">
        <AlertDialogHeader className="px-4 pt-4">
          <AlertDialogTitle className="flex items-center gap-2 text-base">
            <Folder size={16} weight="regular" />
            Add folder to chat
          </AlertDialogTitle>
          <AlertDialogDescription className="text-(--gray-11) text-sm">
            The agent will be able to read and write files in this folder.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="px-4">
          <div
            className="min-w-0 truncate rounded-(--radius-2) border border-(--gray-5) bg-(--gray-3) px-2 py-1.5 font-mono text-[12px]"
            title={path}
          >
            {path}
          </div>
        </div>

        <AlertDialogFooter className="border-t-0 bg-transparent">
          <Button variant="outline" size="sm" onClick={handleCancel}>
            Cancel
          </Button>
          <Button variant="outline" size="sm" onClick={handleAlways}>
            Always add to new chats
          </Button>
          <Button
            ref={justThisChatRef}
            variant="primary"
            size="sm"
            onClick={handleJustThisChat}
          >
            Just this chat
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
