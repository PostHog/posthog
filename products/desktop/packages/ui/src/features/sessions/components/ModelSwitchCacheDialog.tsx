import { ArrowRight } from "@phosphor-icons/react";
import { relativeCostLabel } from "@posthog/core/billing/modelPricing";
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
  fromModelId: string;
  fromModelLabel: string;
  toModelId: string;
  toModelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Inform-only pause before a mid-session model switch: the switch always
 * goes through on confirm; the dialog only explains the cache cost and, when
 * both list prices are known, the relative per-token rate.
 */
export function ModelSwitchCacheDialog({
  open,
  fromModelId,
  fromModelLabel,
  toModelId,
  toModelLabel,
  onConfirm,
  onCancel,
}: ModelSwitchCacheDialogProps): ReactElement {
  const setWarnOnModelSwitch = useSettingsStore(
    (state) => state.setWarnOnMidSessionModelSwitch,
  );
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const checkboxId = useId();
  const rateLabel = relativeCostLabel(fromModelId, toModelId);

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
        <div className="flex flex-col gap-2 rounded-(--radius-3) border border-(--gray-4) bg-(--gray-2) px-4 py-3">
          <div className="flex items-center justify-center gap-2.5">
            <span className="rounded-(--radius-2) bg-(--gray-4) px-2 py-1 text-[12px] text-muted-foreground">
              {fromModelLabel}
            </span>
            <ArrowRight size={13} className="shrink-0 text-muted-foreground" />
            <span className="rounded-(--radius-2) bg-(--gray-4) px-2 py-1 font-medium text-[12px] text-foreground">
              {toModelLabel}
            </span>
          </div>
          {rateLabel && (
            <Text className="text-center text-[12px] text-muted-foreground">
              {toModelLabel} runs at about{" "}
              <span className="font-medium text-foreground tabular-nums">
                {rateLabel}
              </span>{" "}
              {fromModelLabel}'s per-token rate.
            </Text>
          )}
        </div>
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
