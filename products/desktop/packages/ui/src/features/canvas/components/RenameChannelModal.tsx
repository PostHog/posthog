import { XIcon } from "@phosphor-icons/react";
import { validateChannelName } from "@posthog/core/canvas/channelName";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldError,
  FieldLabel,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
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
      <DialogContent className="max-w-[560px]" showCloseButton={false}>
        <DialogHeader className="flex-row items-start justify-between gap-3">
          <DialogTitle>Rename {spacesLayout ? "space" : "channel"}</DialogTitle>
          <DialogClose
            render={
              <Button
                type="button"
                variant="default"
                size="icon-sm"
                aria-label="Close"
                disabled={isRenaming}
              />
            }
          >
            <XIcon />
          </DialogClose>
        </DialogHeader>

        <DialogBody>
          <Field>
            <FieldLabel htmlFor="rename-channel-name">Name</FieldLabel>
            <InputGroup>
              <InputGroupAddon align="inline-start">
                {channelGlyph(channel.name, {
                  personal: channel.channelType === "personal",
                  private: channel.channelType === "private",
                  size: 16,
                  space: spacesLayout,
                })}
              </InputGroupAddon>
              <InputGroupInput
                id="rename-channel-name"
                autoFocus
                value={name}
                placeholder="e.g. mobile"
                maxLength={MAX_CHANNEL_NAME_LENGTH}
                disabled={isRenaming}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void submit();
                  }
                }}
              />
              <InputGroupAddon align="inline-end">
                <InputGroupText className="tabular-nums">
                  {remaining}
                </InputGroupText>
              </InputGroupAddon>
            </InputGroup>
            {validationError && <FieldError>{validationError}</FieldError>}
          </Field>
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
