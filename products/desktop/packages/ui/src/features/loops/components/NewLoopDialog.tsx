import { channelDisplayReference } from "@posthog/core/canvas/channelName";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { navigateToLoopDetail } from "@posthog/ui/router/navigationBridge";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Theme } from "@radix-ui/themes";
import { useLoopWizardDialogStore } from "../loopWizardDialogStore";
import { LoopForm } from "./LoopForm";

export function NewLoopDialog() {
  const open = useLoopWizardDialogStore((state) => state.open);
  const spaceName = useLoopWizardDialogStore((state) => state.spaceName);
  const close = useLoopWizardDialogStore((state) => state.close);
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const spaceReference = spaceName ? channelDisplayReference(spaceName) : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent
        size="wide"
        showCloseButton={false}
        className="flex max-h-[88vh] w-full max-w-[680px] flex-col gap-0 overflow-hidden p-0"
      >
        <DialogHeader className="border-border border-b px-6 pt-5 pb-4">
          <DialogTitle>
            {spaceReference
              ? `New loop for ${spaceReference}`
              : "New global loop"}
          </DialogTitle>
          {spaceReference ? (
            <DialogDescription>
              This loop works for {spaceReference} and posts to its feed.
            </DialogDescription>
          ) : null}
        </DialogHeader>
        {open ? (
          <Theme
            appearance={isDarkMode ? "dark" : "light"}
            accentColor={isDarkMode ? "yellow" : "orange"}
            grayColor="slate"
            panelBackground="solid"
            radius="medium"
            scaling="105%"
            hasBackground={false}
            className="flex min-h-0 flex-1 flex-col"
          >
            <LoopForm
              frame="dialog"
              onCancel={close}
              onSaved={(loop) => {
                close();
                navigateToLoopDetail(loop.id, {
                  channelId: loop.context_target?.channel_id,
                });
              }}
            />
          </Theme>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
