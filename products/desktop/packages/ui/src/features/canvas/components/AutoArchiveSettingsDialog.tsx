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
  FieldContent,
  FieldDescription,
  FieldLabel,
  NumberFieldGroup,
  NumberFieldInput,
  NumberFieldRoot,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@posthog/quill";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useEffect, useState } from "react";

export type AutoArchiveAfterDays = number;

const CUSTOM = "custom";
const MIN_THRESHOLD_DAYS = 1;
const MAX_THRESHOLD_DAYS = 365;
const DEFAULT_THRESHOLD_DAYS = 7;
const PRESET_DAYS = new Set([1, 3, 7, 14, 30]);
const OPTIONS: { value: string; label: string }[] = [
  { value: "1", label: "After 1 day" },
  { value: "3", label: "After 3 days" },
  { value: "7", label: "After 7 days" },
  { value: "14", label: "After 14 days" },
  { value: "30", label: "After 30 days" },
  { value: CUSTOM, label: "Custom…" },
];

function toSelection(days: AutoArchiveAfterDays | null | undefined): string {
  if (days == null) return String(DEFAULT_THRESHOLD_DAYS);
  return PRESET_DAYS.has(days) ? String(days) : CUSTOM;
}

function toCustomDays(
  days: AutoArchiveAfterDays | null | undefined,
): number | null {
  return days != null && !PRESET_DAYS.has(days) ? days : null;
}

function isValidThreshold(days: number | null): days is number {
  return (
    days !== null &&
    Number.isInteger(days) &&
    days >= MIN_THRESHOLD_DAYS &&
    days <= MAX_THRESHOLD_DAYS
  );
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
  const currentDays = channel.autoArchiveAfterDays ?? null;
  const currentSelection = toSelection(currentDays);
  const [enabled, setEnabled] = useState(currentDays !== null);
  const [selection, setSelection] = useState(currentSelection);
  const [customDays, setCustomDays] = useState<number | null>(() =>
    toCustomDays(currentDays),
  );

  useEffect(() => {
    if (open) {
      setEnabled(currentDays !== null);
      setSelection(currentSelection);
      setCustomDays(toCustomDays(currentDays));
    }
  }, [currentDays, currentSelection, open]);

  const selectedDays = !enabled
    ? null
    : selection === CUSTOM
      ? isValidThreshold(customDays)
        ? customDays
        : undefined
      : Number(selection);
  const isUnchanged = selectedDays === currentDays;

  const submit = async (): Promise<void> => {
    if (isSaving || selectedDays === undefined || isUnchanged) return;
    if (await onSave(selectedDays)) onOpenChange(false);
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
          <Field orientation="horizontal">
            <FieldContent>
              <FieldLabel htmlFor="auto-archive-enabled">
                Auto-archive inactive tasks
              </FieldLabel>
              <FieldDescription>
                Turn this on to archive finished tasks after a period of
                inactivity.
              </FieldDescription>
            </FieldContent>
            <Switch
              id="auto-archive-enabled"
              size="sm"
              checked={enabled}
              onCheckedChange={setEnabled}
              disabled={isSaving}
            />
          </Field>
          {enabled && (
            <Field>
              <FieldLabel htmlFor="auto-archive-after-days">
                Inactivity period
              </FieldLabel>
              <Select
                value={selection}
                onValueChange={(next) =>
                  setSelection(next ?? String(DEFAULT_THRESHOLD_DAYS))
                }
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
                New messages and task runs reset this period. Tasks being
                viewed, pinned, or actively running are not archived.
              </FieldDescription>
            </Field>
          )}
          {enabled && selection === CUSTOM && (
            <Field orientation="horizontal">
              <FieldContent>
                <FieldLabel htmlFor="custom-auto-archive-days">
                  Days of inactivity before auto-archive
                </FieldLabel>
                <FieldDescription>
                  Choose a value from 1 to 365 days.
                </FieldDescription>
              </FieldContent>
              <NumberFieldRoot
                id="custom-auto-archive-days"
                value={customDays}
                onValueChange={setCustomDays}
                min={MIN_THRESHOLD_DAYS}
                max={MAX_THRESHOLD_DAYS}
                step={1}
                disabled={isSaving}
                className="w-20 shrink-0"
              >
                <NumberFieldGroup>
                  <NumberFieldInput className="text-start" />
                </NumberFieldGroup>
              </NumberFieldRoot>
            </Field>
          )}
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
            disabled={selectedDays === undefined || isUnchanged}
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
