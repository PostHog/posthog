import { validateChannelName } from "@posthog/core/canvas/channelName";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useState } from "react";

// Matches the create-channel naming constraint.
const MAX_CHANNEL_NAME_LENGTH = 80;

interface RenameChannelModalProps {
  channel: Channel;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RenameChannelModal({
  channel,
  open,
  onOpenChange,
}: RenameChannelModalProps) {
  const { renameChannel, isRenaming } = useChannelMutations();
  const spacesLayout = useChannelsLayout();
  const [name, setName] = useState(channel.name);

  // Seed the field with the current name each time the modal opens.
  useEffect(() => {
    if (open) setName(channel.name);
  }, [open, channel.name]);

  const trimmed = name.trim();
  const remaining = MAX_CHANNEL_NAME_LENGTH - name.length;
  const unchanged = trimmed === channel.name;
  const validationError = validateChannelName(trimmed);

  const submit = async () => {
    if (!trimmed || unchanged || validationError || isRenaming) return;
    try {
      await renameChannel(channel.id, trimmed);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "rename",
        surface: "sidebar",
        channel_id: channel.id,
        success: true,
      });
      onOpenChange(false);
    } catch (error) {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "rename",
        surface: "sidebar",
        channel_id: channel.id,
        success: false,
      });
      toast.error(`Couldn't rename ${spacesLayout ? "space" : "channel"}`, {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isRenaming) onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-[560px]" showCloseButton={!isRenaming}>
        <DialogHeader>
          <DialogTitle>Rename {spacesLayout ? "space" : "channel"}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-2">
            <label
              htmlFor="rename-channel-name"
              className="font-medium text-sm"
            >
              Name
            </label>
            <div className="relative">
              <span className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-3">
                {channelGlyph(channel.name, {
                  personal: channel.channelType === "personal",
                  private: channel.channelType === "private",
                  size: 16,
                  space: spacesLayout,
                })}
              </span>
              <Input
                id="rename-channel-name"
                autoFocus
                value={name}
                placeholder="e.g. mobile"
                maxLength={MAX_CHANNEL_NAME_LENGTH}
                disabled={isRenaming}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void submit();
                  }
                }}
                className="pr-12 pl-10"
              />
              <span className="-translate-y-1/2 pointer-events-none absolute top-1/2 right-3 text-muted-foreground text-sm tabular-nums">
                {remaining}
              </span>
            </div>
            {validationError && (
              <p className="text-destructive text-sm">{validationError}</p>
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button
            variant="primary"
            loading={isRenaming}
            disabled={!trimmed || unchanged || !!validationError || isRenaming}
            onClick={submit}
          >
            Rename
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
