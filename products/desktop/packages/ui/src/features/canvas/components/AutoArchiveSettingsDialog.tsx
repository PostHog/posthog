import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldDescription,
  FieldLabel,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useEffect, useState } from "react";

export type AutoArchiveAfterDays = 1 | 3 | 7 | 14 | 30;

const NEVER = "never";
const OPTIONS: { value: string; label: string }[] = [
  { value: NEVER, label: "Never" },
  { value: "1", label: "After 1 day" },
  { value: "3", label: "After 3 days" },
  { value: "7", label: "After 7 days" },
  { value: "14", label: "After 14 days" },
  { value: "30", label: "After 30 days" },
];

function toValue(days: AutoArchiveAfterDays | null | undefined): string {
  return days == null ? NEVER : String(days);
}

export function AutoArchiveSettingsDialog({
  channel,
  open,
  onOpenChange,
  onSave,
  isSaving,
}: {
  channel: Channel;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (days: AutoArchiveAfterDays | null) => Promise<boolean>;
  isSaving: boolean;
}) {
  const currentValue = toValue(channel.autoArchiveAfterDays);
  const [value, setValue] = useState(currentValue);

  useEffect(() => {
    if (open) setValue(currentValue);
  }, [currentValue, open]);

  const submit = async (): Promise<void> => {
    if (isSaving || value === currentValue) return;
    const days =
      value === NEVER ? null : (Number(value) as AutoArchiveAfterDays);
    if (await onSave(days)) onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isSaving) onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Auto-archive tasks</DialogTitle>
          <DialogDescription>
            Choose when inactive tasks in {channel.name} are archived. This
            setting applies to{" "}
            {channel.channelType === "personal"
              ? "your personal space"
              : "everyone in this space"}
            .
          </DialogDescription>
        </DialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-3">
          <Field>
            <FieldLabel htmlFor="auto-archive-after-days">
              Inactivity period
            </FieldLabel>
            <Select
              value={value}
              onValueChange={(next) => setValue(next ?? NEVER)}
              items={OPTIONS}
              disabled={isSaving}
            >
              <SelectTrigger
                id="auto-archive-after-days"
                aria-label="Inactivity period"
                className="w-full"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent align="start" side="bottom" sideOffset={6}>
                {OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldDescription>
              New messages and task runs reset this period. Tasks being viewed,
              pinned, or actively running are not archived.
            </FieldDescription>
          </Field>
        </DialogBody>
        <DialogFooter>
          <DialogClose
            render={
              <Button variant="outline" disabled={isSaving}>
                Cancel
              </Button>
            }
          />
          <Button
            variant="primary"
            loading={isSaving}
            disabled={value === currentValue}
            data-attr="save-space-auto-archive"
            onClick={() => void submit()}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
