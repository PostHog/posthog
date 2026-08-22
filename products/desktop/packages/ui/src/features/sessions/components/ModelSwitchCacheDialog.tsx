import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Checkbox,
  Text,
} from "@posthog/quill";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { type ReactElement, useId, useState } from "react";

interface ModelSwitchCacheDialogProps {
  open: boolean;
  /** Display name of the model being switched to. */
  toModelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Inform-only pause before a mid-session model switch: the switch always
 * goes through on confirm; the dialog only explains the cache cost.
 */
export function ModelSwitchCacheDialog({
  open,
  toModelLabel,
  onConfirm,
  onCancel,
}: ModelSwitchCacheDialogProps): ReactElement {
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const checkboxId = useId();

  const rememberChoice = () => {
    if (dontShowAgain) setWarnOnModelSwitch(false);
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Switch model mid-session?</AlertDialogTitle>
          <AlertDialogDescription>
            Cached context doesn't carry over between models. Your next message
            will reprocess the whole conversation instead of reading it from
            cache, which costs more on long sessions.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex items-center gap-2">
          <Checkbox
            id={checkboxId}
            checked={dontShowAgain}
            onCheckedChange={(checked) => setDontShowAgain(checked === true)}
            data-attr="model-switch-cache-dialog-dont-show-again"
          />
          <label htmlFor={checkboxId}>
            <Text className="text-[13px] text-muted-foreground">
              Don't show this again
            </Text>
          </label>
        </div>
        <AlertDialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              rememberChoice();
              onCancel();
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            data-attr="model-switch-cache-dialog-confirm"
            onClick={() => {
              rememberChoice();
              onConfirm();
            }}
          >
            Switch to {toModelLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
